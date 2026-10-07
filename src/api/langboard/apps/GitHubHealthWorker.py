"""One leased receipt page per task; indexed recovery of lost dispatches."""

from datetime import timedelta
from uuid import uuid4
from langboard_shared.core.db import DbSession, SqlBuilder
from langboard_shared.core.types import SafeDateTime
from langboard_shared.domain.models import AppResourceBinding, BoardAppBinding, GitHubHealthJob, GitHubLifecycleReceipt
from langboard_shared.helpers import InfraHelper
from sqlalchemy import select, update
from .GitHubHealth import refresh_receipt_resources
from .GitHubManifest import GitHubManifestUnavailable
from .GitHubResources import GitHubNoSelectedRepositories


MAX_ATTEMPTS = 4
LEASE_SECONDS = 300


def enqueue(job_uid):
    from .GitHubHealthTask import github_health_task

    github_health_task(job_uid)


def schedule_receipt(db, receipt):
    """Job and receipt commit together; dispatch is best effort after commit."""
    if receipt.event == "ping":
        return
    existing = db.exec(SqlBuilder.select.table(GitHubHealthJob).where(GitHubHealthJob.receipt_id == receipt.id)).first()
    if existing is not None:
        return
    job = GitHubHealthJob(receipt_id=receipt.id, available_at=SafeDateTime.now())
    db.insert(job)
    db.after_commit(lambda: enqueue(job.get_uid()))


def _eligible(now):
    return GitHubHealthJob.state.in_(["pending", "processing"]) & (GitHubHealthJob.available_at <= now)


def recover_pending(limit=100):
    """Only due job rows; never reconcile every resource or attachment."""
    if type(limit) is not int or not 1 <= limit <= 100:
        raise ValueError("Invalid recovery limit")
    with DbSession.use(readonly=False) as db:
        jobs = db.exec(
            SqlBuilder.select.table(GitHubHealthJob)
            .where(_eligible(SafeDateTime.now()))
            .order_by(GitHubHealthJob.available_at, GitHubHealthJob.id)
            .limit(limit)
        ).all()
    queued = 0
    for job in jobs:
        try:
            enqueue(job.get_uid())
            queued += 1
        except Exception:
            # Durable due row remains available to the next recovery tick.
            continue
    return queued


def _next_board(db, receipt, after):
    resources = AppResourceBinding
    query = (
        select(BoardAppBinding.project_id)
        .join(resources, resources.board_binding_id == BoardAppBinding.id)
        .where(
            BoardAppBinding.app_key == "github",
            BoardAppBinding.project_id > after,
            resources.connection_id == receipt.connection_id,
            resources.resource_type == "repository",
            resources.is_selected == True,  # noqa: E712
            resources.resource_path[0]["id"].as_string() == receipt.installation_id,
            resources.resource_path[1]["id"].as_string() == receipt.account_id,
        )
        .order_by(BoardAppBinding.project_id)
        .limit(1)
    )
    if receipt.event == "installation_repositories":
        query = query.where(
            resources.external_resource_id.in_(
                [str(value) for value in (*receipt.added_repository_ids, *receipt.removed_repository_ids)]
            )
        )
    row = db.exec(query).first()
    return int(row[0]) if row is not None else None


def drain_one(service, job_uid):
    now, token = SafeDateTime.now(), uuid4().hex
    with DbSession.atomic() as db:
        job = db.exec(
            SqlBuilder.select.table(GitHubHealthJob)
            .where(GitHubHealthJob.id == InfraHelper.convert_id(job_uid), _eligible(now))
            .with_for_update()
        ).first()
        if job is None or job.state not in {"pending", "processing"}:
            return False
        if job.attempts >= MAX_ATTEMPTS:
            job.state, job.last_error = "failed", "attempts_exhausted"
            db.update(job)
            return True
        receipt = db.exec(
            SqlBuilder.select.table(GitHubLifecycleReceipt).where(GitHubLifecycleReceipt.id == job.receipt_id)
        ).first()
        if receipt is None or not receipt.invalidated or receipt.event == "ping":
            job.state, job.last_error = "blocked", "receipt_unavailable"
            db.update(job)
            return True
        project_id = job.project_id if job.project_id is not None else _next_board(db, receipt, job.board_after)
        if project_id is None:
            job.state = "blocked" if job.blocked_boards else "completed"
            db.update(job)
            return True
        claimed = db.exec(
            update(GitHubHealthJob)
            .where(GitHubHealthJob.id == job.id, _eligible(now))
            .values(
                state="processing",
                lease_token=token,
                attempts=job.attempts + 1,
                available_at=now + timedelta(seconds=LEASE_SECONDS),
                project_id=project_id,
                updated_at=now,
            ),
            execution_options={"synchronize_session": False},
        )
        if claimed != 1:
            return False
        receipt_uid, project_uid, cursor = (
            receipt.get_uid(),
            InfraHelper.convert_uid(project_id),
            job.resource_after,
        )
    result, error = None, None
    try:
        result = refresh_receipt_resources(service, receipt_uid, project_uid, cursor)
        if result.get("unavailable_count", 0):
            error = "api_unavailable"
    except GitHubNoSelectedRepositories:
        result = {"next_cursor": None}
    except GitHubManifestUnavailable:
        error = "authority_unavailable"
    except ValueError:
        # A selected cursor can disappear. Restart only this board, under the attempt cap.
        error = "selection_changed"
    except Exception as failure:
        error = type(failure).__name__[:80]
    with DbSession.atomic() as db:
        job = db.exec(
            SqlBuilder.select.table(GitHubHealthJob)
            .where(GitHubHealthJob.id == InfraHelper.convert_id(job_uid))
            .with_for_update()
        ).first()
        if job is None or job.state != "processing" or job.lease_token != token:
            return False
        job.lease_token, job.last_error = None, error
        if error == "authority_unavailable":
            # One board losing authority must not prevent other authorized boards from refreshing.
            job.blocked_boards += 1
            job.state, job.attempts = "pending", 0
            job.board_after, job.project_id, job.resource_after = job.project_id, None, None
            job.available_at = SafeDateTime.now()
            db.after_commit(lambda: enqueue(job_uid))
        elif error:
            job.state = "failed" if job.attempts >= MAX_ATTEMPTS else "pending"
            job.available_at = SafeDateTime.now() + timedelta(seconds=30 * 2 ** (job.attempts - 1))
            if error == "selection_changed":
                job.resource_after = None
        else:
            job.state, job.attempts = "pending", 0
            job.available_at = SafeDateTime.now()
            job.resource_after = result["next_cursor"]
            if job.resource_after is None:
                job.board_after, job.project_id = job.project_id, None
            db.after_commit(lambda: enqueue(job_uid))
        db.update(job)
    return True


if __name__ == "__main__":
    print(f"queued={recover_pending()}")
