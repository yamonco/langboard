"""Explicit, current-authority start permits and stop-only recovery credentials."""

import re
from datetime import timedelta, timezone
from hashlib import sha256
from hmac import compare_digest
from ...core.db import DbSession, SqlBuilder
from ...core.types import SafeDateTime
from ..models import (
    AppConnection,
    AppConnectionCredential,
    AppExecutionAcknowledgment,
    AppExecutionLease,
    AppExecutionRequest,
)
from .AppConnectionAuthentication import _identity_hash, authenticate_connection_credential
from .AppEventDelivery import _expired
from .AppExecutionAcknowledgments import _request
from .AppExecutionGrant import evaluate_connection_execution_grant
from .AppExecutionRequests import AppExecutionRequestConflict
from .AppGovernance import AppGovernanceDenied


LEASE_SECONDS = 120


def runtime_timestamp(value):
    """Writers store UTC; SQLite reloads naive values. Wire timestamps stay aware."""
    return (value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value).isoformat()


def _hash(token):
    if not isinstance(token, str) or not re.fullmatch(r"[0-9a-f]{64}", token):
        raise ValueError("Runtime token must be 32 random bytes encoded as lowercase hex")
    return sha256(token.encode()).hexdigest()


def _result(db, row):
    request = db.exec(
        SqlBuilder.select.table(AppExecutionRequest).where(AppExecutionRequest.id == row.request_id)
    ).first()
    ack = db.exec(
        SqlBuilder.select.table(AppExecutionAcknowledgment).where(
            AppExecutionAcknowledgment.id == row.acknowledgment_id
        )
    ).first()
    if request is None or ack is None or ack.request_id != request.id:
        raise AppGovernanceDenied()
    return {
        "schema_version": 1,
        "request_uid": request.get_uid(),
        "acknowledgment_uid": ack.get_uid(),
        "runtime_reference": ack.runtime_reference,
        "generation": request.generation,
        "lease_uid": row.get_uid(),
        "state": row.state,
        "permit_execution": row.state == "authorized",
        "started": False,
        "expires_at": runtime_timestamp(row.expires_at),
    }


def authorize_app_runtime(token, project_id, card_id, request_id, acknowledgment_id, runtime_token):
    digest = _hash(runtime_token)
    with DbSession.atomic() as db:
        request = _request(db, token, project_id, card_id, request_id)
        principal = authenticate_connection_credential(token)
        db.exec(
            SqlBuilder.select.table(AppConnectionCredential)
            .where(AppConnectionCredential.id == principal.credential_id)
            .with_for_update()
        ).first()
        # Serialize revocation with creation and recheck after acquiring its lock.
        principal = authenticate_connection_credential(token)
        ack = db.exec(
            SqlBuilder.select.table(AppExecutionAcknowledgment).where(
                AppExecutionAcknowledgment.id == acknowledgment_id,
                AppExecutionAcknowledgment.request_id == request.id,
            )
        ).first()
        if ack is None or ack.connection_id != request.connection_id or ack.app_key != request.app_key:
            raise AppGovernanceDenied()
        row = db.exec(
            SqlBuilder.select.table(AppExecutionLease)
            .where(
                AppExecutionLease.request_id == request.id,
            )
            .with_for_update()
        ).first()
        if row:
            if (
                not compare_digest(row.runtime_token_hash, digest)
                or row.credential_id != principal.credential_id
                or row.acknowledgment_id != ack.id
                or row.state != "authorized"
                or _expired(row.expires_at, SafeDateTime.now())
            ):
                raise AppExecutionRequestConflict()
            return {**_result(db, row), "changed": False}
        now = SafeDateTime.now()
        row = AppExecutionLease(
            request_id=request.id,
            acknowledgment_id=ack.id,
            credential_id=principal.credential_id,
            runtime_token_hash=digest,
            expires_at=now + timedelta(seconds=LEASE_SECONDS),
            history=[{"state": "authorized", "at": now.isoformat()}],
        )
        db.insert(row)
        return {**_result(db, row), "changed": True}


def check_app_runtime(lease_id, runtime_token, *, stopped=False):
    """Opaque token may check/stop only this runtime after its app credential is revoked."""
    return _check_app_runtime(lease_id, runtime_token, stopped=stopped, renew=True)


def _check_app_runtime(lease_id, runtime_token, *, stopped=False, renew=False):
    if type(stopped) is not bool:
        raise ValueError("Stopped must be a boolean")
    digest = _hash(runtime_token)
    with DbSession.atomic() as db:
        # Same project/card -> lease lock order as authorize to avoid lock inversion.
        initial = db.exec(SqlBuilder.select.table(AppExecutionLease).where(AppExecutionLease.id == lease_id)).first()
        if initial is None or not compare_digest(initial.runtime_token_hash, digest):
            raise AppGovernanceDenied()
        request = db.exec(
            SqlBuilder.select.table(AppExecutionRequest).where(AppExecutionRequest.id == initial.request_id)
        ).first()
        allowed = False
        if not stopped and initial.state == "authorized" and request is not None:
            try:
                current = evaluate_connection_execution_grant(
                    request.connection_id, request.project_id, request.card_id, request.generation
                )
                allowed = current["authority_version"] == request.authority.get("authority_version")
                credential = db.exec(
                    SqlBuilder.select.table(AppConnectionCredential)
                    .where(AppConnectionCredential.id == initial.credential_id)
                    .with_for_update()
                ).first()
                connection = db.exec(
                    SqlBuilder.select.table(AppConnection).where(AppConnection.id == request.connection_id)
                ).first()
                allowed = bool(
                    allowed
                    and credential is not None
                    and connection is not None
                    and credential.connection_id == request.connection_id
                    and credential.revoked_at is None
                    and not _expired(credential.expires_at, SafeDateTime.now())
                    and credential.identity_hash == _identity_hash(db, connection)
                )
            except AppGovernanceDenied:
                pass
        row = db.exec(
            SqlBuilder.select.table(AppExecutionLease).where(AppExecutionLease.id == lease_id).with_for_update()
        ).first()
        now = SafeDateTime.now()
        new_state = row.state
        if stopped:
            new_state = "stopped"
        elif row.state == "authorized" and (not allowed or _expired(row.expires_at, now)):
            new_state = "stop_requested"
        if new_state != row.state:
            row.state = new_state
            row.history = [*row.history, {"state": new_state, "at": now.isoformat()}]
            db.update(row)
        elif renew and not stopped and row.state == "authorized" and allowed and not _expired(row.expires_at, now):
            row.expires_at = now + timedelta(seconds=LEASE_SECONDS)
            db.update(row)
        # Only a still-valid current-authority heartbeat renews. Expired/stopped
        # permits never resume; a new generation requires explicit acceptance.
        return _result(db, row)


def recover_app_runtime(request_id, runtime_token):
    """Resolve a lost permit response without creating or rotating a runtime."""
    digest = _hash(runtime_token)
    with DbSession.use(readonly=False) as db:
        row = db.exec(
            SqlBuilder.select.table(AppExecutionLease).where(AppExecutionLease.request_id == request_id)
        ).first()
        if row is None or not compare_digest(row.runtime_token_hash, digest):
            raise AppGovernanceDenied()
        lease_id = row.id
    # Return only after the normal current-authority/expiry fence. Stop-only
    # recovery survives app credential revocation and cannot authorize a new lease.
    return check_app_runtime(lease_id, runtime_token)
