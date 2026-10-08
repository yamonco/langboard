"""One current-authority resource per leased task; no raw webhook payload replay."""
import re
from datetime import timedelta
from uuid import uuid4
from langboard_shared.core.db import DbSession, SqlBuilder
from langboard_shared.core.types import SafeDateTime
from langboard_shared.domain.models import (
    AppConnection,
    AppResourceBinding,
    AppSignal,
    BoardAppBinding,
    GitHubSignalDelivery,
    User,
)
from langboard_shared.domain.services.factory.SecretReferenceService import SecretReferenceUnavailable
from langboard_shared.helpers import InfraHelper
from sqlalchemy import select, update
from .GitHubInstallation import connection_revision
from .GitHubLifecycle import GitHubDeliveryConflict, _positive, verify_signed_payload
from .GitHubManifest import GitHubManifestUnavailable
from .GitHubSignal import _scope, normalize_check


MAX_ATTEMPTS = 4


def enqueue(uid):
    from .GitHubHealthTask import github_signal_task
    github_signal_task(uid)


def _resources(connection_id, installation_id, account_id, repository_id):
    return (
        select(AppResourceBinding.id, BoardAppBinding.project_id)
        .join(BoardAppBinding, BoardAppBinding.id == AppResourceBinding.board_binding_id)
        .where(
            BoardAppBinding.app_key == "github", AppResourceBinding.connection_id == connection_id,
            AppResourceBinding.resource_type == "repository", AppResourceBinding.external_resource_id == repository_id,
            AppResourceBinding.resource_path[0]["id"].as_string() == installation_id,
            AppResourceBinding.resource_path[1]["id"].as_string() == account_id,
        )
    )


def receive_external_check(service, body, signature, event, delivery_id, target_app_id):
    try:
        if event != "check_run" or not isinstance(target_app_id, str) or not re.fullmatch(r"[1-9][0-9]{0,19}", target_app_id):
            raise GitHubManifestUnavailable()
        with DbSession.use(readonly=False) as db:
            candidates = db.exec(SqlBuilder.select.table(AppConnection).where(
                AppConnection.app_key == "github", AppConnection.external_account_id == target_app_id,
                AppConnection.state == "connected",
            ).limit(2)).all()
            if len(candidates) != 1:
                raise GitHubManifestUnavailable()
            connection = candidates[0]
            actor = db.exec(SqlBuilder.select.table(User).where(User.id == connection.owner_id)).first()
            if actor is None or actor.deleted_at or not actor.activated_at:
                raise GitHubManifestUnavailable()
        meta = service.secret_reference.get_metadata(actor, connection.credential_reference)
        payload, connection, revision, app_id = verify_signed_payload(
            service, actor, connection.get_uid(), body, signature, delivery_id,
        )
        if str(app_id) != target_app_id:
            raise GitHubManifestUnavailable()
        installation_id = str(_positive(payload["installation"]["id"]))
        account_id = str(_positive(payload["repository"]["owner"]["id"]))
        repository_id = str(_positive(payload["repository"]["id"]))
        if payload.get("action") in {"created", "rerequested", "requested_action"}:
            # A check_run subscription also delivers actions outside the current completion adapter.
            return {"ignored": True}
        evidence = normalize_check(payload, body, delivery_id)
    except Exception:
        raise GitHubManifestUnavailable() from None
    with DbSession.atomic() as db:
        actor = db.exec(SqlBuilder.select.table(User).where(User.id == actor.id).with_for_update()).first()
        if actor is None or actor.deleted_at or not actor.activated_at:
            raise GitHubManifestUnavailable()
        current = db.exec(SqlBuilder.select.table(AppConnection).where(AppConnection.id == connection.id).with_for_update()).first()
        if current is None or current.state != "connected" or connection_revision(current) != revision:
            raise GitHubManifestUnavailable()
        try:
            secret = service.secret_reference._find(actor, current.credential_reference, lock=True)
        except Exception:
            raise GitHubManifestUnavailable() from None
        if secret.state != "active" or secret.revision != meta["revision"]:
            raise GitHubManifestUnavailable()
        prior = db.exec(SqlBuilder.select.table(GitHubSignalDelivery).where(
            GitHubSignalDelivery.connection_id == current.id, GitHubSignalDelivery.event_id == evidence["event_id"],
        )).first()
        if prior is not None:
            if prior.evidence != evidence or (prior.installation_id, prior.account_id, prior.repository_id) != (installation_id, account_id, repository_id):
                raise GitHubDeliveryConflict()
            return {"delivery_uid": prior.get_uid(), "duplicate": True}
        last = db.exec(_resources(current.id, installation_id, account_id, repository_id).order_by(AppResourceBinding.id.desc()).limit(1)).first()
        delivery = GitHubSignalDelivery(
            connection_id=current.id, connection_revision=revision, secret_revision=secret.revision,
            event_id=evidence["event_id"], installation_id=installation_id, account_id=account_id,
            repository_id=repository_id, evidence=evidence, resource_upper=int(last[0]) if last else 0,
            available_at=SafeDateTime.now(),
        )
        db.insert(delivery)
        db.after_commit(lambda: enqueue(delivery.get_uid()))
        return {"delivery_uid": delivery.get_uid(), "duplicate": False}


def _eligible(now):
    return GitHubSignalDelivery.state.in_(["pending", "processing"]) & (GitHubSignalDelivery.available_at <= now)


def recover_pending(limit=100):
    if type(limit) is not int or not 1 <= limit <= 100:
        raise ValueError("Invalid recovery limit")
    with DbSession.use(readonly=False) as db:
        jobs = db.exec(SqlBuilder.select.table(GitHubSignalDelivery).where(_eligible(SafeDateTime.now())).order_by(
            GitHubSignalDelivery.available_at, GitHubSignalDelivery.id,
        ).limit(limit)).all()
    queued = 0
    for job in jobs:
        try:
            enqueue(job.get_uid())
            queued += 1
        except Exception:
            continue
    return queued


def drain_one(service, uid):
    now, token = SafeDateTime.now(), uuid4().hex
    with DbSession.atomic() as db:
        job = db.exec(SqlBuilder.select.table(GitHubSignalDelivery).where(
            GitHubSignalDelivery.id == InfraHelper.convert_id(uid), _eligible(now),
        ).with_for_update()).first()
        if job is None:
            return False
        if job.attempts >= MAX_ATTEMPTS:
            job.state, job.last_error = "failed", "attempts_exhausted"
            db.update(job)
            return True
        resource = db.exec(_resources(job.connection_id, job.installation_id, job.account_id, job.repository_id).where(
            AppResourceBinding.id > job.resource_after, AppResourceBinding.id <= job.resource_upper,
        ).order_by(AppResourceBinding.id).limit(1)).first()
        if resource is None:
            job.state = "blocked" if job.skipped_resources else "completed"
            db.update(job)
            return True
        claimed = db.exec(update(GitHubSignalDelivery).where(GitHubSignalDelivery.id == job.id, _eligible(now)).values(
            state="processing", attempts=job.attempts + 1, lease_token=token,
            available_at=now + timedelta(seconds=300), updated_at=now,
        ), execution_options={"synchronize_session": False})
        if claimed != 1:
            return False
        resource_id, project_id = int(resource[0]), int(resource[1])
        connection_uid = InfraHelper.convert_uid(job.connection_id)
        evidence = dict(job.evidence)
        revision, secret_revision = job.connection_revision, job.secret_revision
    try:
        with DbSession.atomic() as db:
            owner, connection, resource = _scope(service, db, InfraHelper.convert_uid(project_id), connection_uid,
                                                 InfraHelper.convert_uid(resource_id), lock=True)
            if connection_revision(connection) != revision:
                raise GitHubManifestUnavailable()
            secret = service.secret_reference._find(owner, connection.credential_reference, lock=True)
            if secret.state != "active" or secret.revision != secret_revision:
                raise GitHubManifestUnavailable()
            if len(resource.resource_path) != 3 or resource.resource_path[0].get("type") != "installation" or resource.resource_path[1].get("type") != "account" or resource.resource_path[2].get("type") != "repository":
                raise GitHubManifestUnavailable()
            current = db.exec(SqlBuilder.select.table(GitHubSignalDelivery).where(
                GitHubSignalDelivery.id == job.id,
            ).with_for_update()).first()
            if current is None or current.state != "processing" or current.lease_token != token:
                return False
            # Recheck resource path after row locking; discovery alone grants no authority.
            if [part.get("id") for part in resource.resource_path] != [current.installation_id, current.account_id, current.repository_id]:
                raise GitHubManifestUnavailable()
            existing = db.exec(SqlBuilder.select.table(AppSignal).where(
                AppSignal.resource_id == resource_id, AppSignal.event_id == evidence["event_id"],
            )).first()
            if existing is not None and any(getattr(existing, key) != value for key, value in evidence.items()):
                raise GitHubDeliveryConflict()
            if existing is None:
                db.insert(AppSignal(resource_id=resource_id, **evidence))
            _advance(db, current, resource_id, None, uid)
        return True
    except Exception as failure:
        if isinstance(failure, (GitHubManifestUnavailable, SecretReferenceUnavailable)):
            error = "authority_unavailable"
        elif isinstance(failure, GitHubDeliveryConflict):
            error = "delivery_conflict"
        else:
            error = "processing_failed"
        with DbSession.atomic() as db:
            current = db.exec(SqlBuilder.select.table(GitHubSignalDelivery).where(
                GitHubSignalDelivery.id == job.id,
            ).with_for_update()).first()
            if current is None or current.state != "processing" or current.lease_token != token:
                return False
            if error == "authority_unavailable":
                current.skipped_resources += 1
                _advance(db, current, resource_id, error, uid)
            else:
                current.state = "failed" if current.attempts >= MAX_ATTEMPTS else "pending"
                current.lease_token, current.last_error = None, error
                current.available_at = SafeDateTime.now() + timedelta(seconds=30 * 2 ** (current.attempts - 1))
                db.update(current)
        return True


def _advance(db, job, resource_id, error, uid):
    job.resource_after, job.state, job.attempts = resource_id, "pending", 0
    job.lease_token, job.last_error, job.available_at = None, error, SafeDateTime.now()
    db.update(job)
    db.after_commit(lambda: enqueue(uid))
