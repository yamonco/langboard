"""Claim committed work.ready rows and deliver them over signed HTTP in one task."""

import argparse
from asyncio import run as run_async
from dataclasses import dataclass
from datetime import timezone
from uuid import UUID
from sqlalchemy import column, func, or_, select, table, text, update
from ...core.db import DbSession
from ...core.types import SnowflakeID
from ...helpers import InfraHelper
from .ExecutionBindingPolicy import binding_for_project, binding_invalid_reasons
from .ExecutionReadinessUow import CurrentExecution, current_execution
from .utils import WebhookModel
from .WebhookTask import post_signed_webhook


OUTBOX = table(
    "execution_outbox",
    column("id"),
    column("project_id"),
    column("card_id"),
    column("execution_generation"),
    column("occurred_at"),
    column("event_type"),
    column("payload_json"),
    column("state"),
    column("last_error"),
    column("processed_at"),
    column("attempt_count"),
    column("lease_until"),
)
PERMANENT_BLOCKS = ("snapshot_unavailable", "destination_unavailable", "stale_binding")
# Initial attempt plus the three Celery retries of execution_outbox_task.
MAX_DELIVERY_ATTEMPTS = 4
# Covers the claim-to-terminal window so a crashed worker loses its claim
# instead of stranding the row. Retries re-claim through 'pending'.
DELIVERY_LEASE_SECONDS = 300


class ExecutionDeliveryFailed(RuntimeError):
    """A claimed execution delivery could not be delivered over HTTP."""


# Distinguishes "claimed a row and closed it without delivery" from "no row left".
_TERMINAL = object()


@dataclass(frozen=True)
class ClaimedDelivery:
    """One transactionally claimed execution event ready for HTTP delivery."""

    event_id: UUID
    model: WebhookModel
    webhook_uid: str


def _mark(db: DbSession, event_id: UUID, state: str, error: str | None = None) -> None:
    db.exec(
        update(OUTBOX).where(OUTBOX.c.id == event_id).values(state=state, last_error=error, processed_at=func.now())
    )


def _event_data(project_id: int, card_id: int, generation: int, current: CurrentExecution) -> dict:
    """Project the claim-time point-read; the outbox row keeps commit-time provenance."""
    project_uid = SnowflakeID(project_id).to_short_code()
    card_uid = SnowflakeID(card_id).to_short_code()
    return {
        "project_uid": project_uid,
        "card_uid": card_uid,
        "execution_generation": generation,
        "title": current.title,
        "labels": current.labels,
        "assignees": [SnowflakeID(uid).to_short_code() for uid in current.assignee_ids],
        "card_url": f"/board/{project_uid}/{card_uid}",
        "source_revision": current.revision.isoformat(),
    }


def _claim(event_id: UUID | None = None) -> ClaimedDelivery | object | None:
    """Claim one eligible row, fence it, and freeze the delivery in one transaction.

    Returns None when no row is eligible, the _TERMINAL sentinel when a row was
    closed without delivery (superseded, blocked, or exhausted), or the frozen
    delivery to POST.
    """
    with DbSession.atomic() as db:
        query = (
            select(
                OUTBOX.c.id,
                OUTBOX.c.project_id,
                OUTBOX.c.card_id,
                OUTBOX.c.execution_generation,
                OUTBOX.c.occurred_at,
                OUTBOX.c.event_type,
                OUTBOX.c.payload_json,
                OUTBOX.c.attempt_count,
            )
            .where(
                or_(
                    OUTBOX.c.state == "pending",
                    (OUTBOX.c.state == "delivering") & (OUTBOX.c.lease_until < func.now()),
                )
            )
            .order_by(OUTBOX.c.occurred_at)
            .limit(1)
            .with_for_update(skip_locked=True)
        )
        if event_id is not None:
            query = query.where(OUTBOX.c.id == event_id)
        row = db.exec(query).first()
        if row is None:
            return None
        event_id, project_id, card_id, generation, occurred_at, event_type, snapshot, attempts = row
        if int(attempts or 0) >= MAX_DELIVERY_ATTEMPTS:
            _mark(db, event_id, "failed", "delivery_attempts_exhausted")
            return _TERMINAL
        if not isinstance(snapshot, dict):
            _mark(db, event_id, "blocked", "snapshot_unavailable")
            return _TERMINAL
        if not all(snapshot.get(key) for key in ("binding_id", "binding_revision", "webhook_uid")):
            _mark(db, event_id, "blocked", "destination_unavailable")
            return _TERMINAL
        current = current_execution(card_id, db)
        # The event is a "this generation is executable" signal, not an
        # immutable snapshot: a READY-preserving content edit must not discard
        # the execution. Only lost readiness or a newer generation supersedes.
        if current is None or not current.is_ready or current.generation != generation:
            _mark(db, event_id, "superseded", "stale_readiness")
            return _TERMINAL
        project_uid = SnowflakeID(project_id).to_short_code()
        binding = binding_for_project(project_uid)
        reasons = binding_invalid_reasons(binding, event_type)
        if reasons:
            _mark(db, event_id, "blocked", ",".join(reasons)[:80])
            return _TERMINAL
        if (
            str(binding.id) != snapshot["binding_id"]
            or binding.updated_at.isoformat() != snapshot["binding_revision"]
            or binding.webhook_uid != snapshot["webhook_uid"]
        ):
            _mark(db, event_id, "blocked", "stale_binding")
            return _TERMINAL
        model = WebhookModel(
            event=event_type,
            event_id=str(event_id),
            occurred_at=occurred_at.astimezone(timezone.utc).isoformat(),
            data=_event_data(project_id, card_id, generation, current),
        )
        db.exec(
            update(OUTBOX)
            .where(OUTBOX.c.id == event_id)
            .values(
                state="delivering",
                attempt_count=int(attempts or 0) + 1,
                lease_until=func.now() + text(f"interval '{DELIVERY_LEASE_SECONDS} seconds'"),
            )
        )
        return ClaimedDelivery(event_id=event_id, model=model, webhook_uid=snapshot["webhook_uid"])


async def drain_one(event_id: UUID | None = None) -> bool:
    """Claim one row and deliver it synchronously; a crash can replay it, so consumers dedupe."""
    claimed = _claim(event_id)
    if claimed is None:
        return False
    if claimed is _TERMINAL:
        return True
    try:
        await post_signed_webhook(claimed.model, claimed.webhook_uid)
    except Exception as error:
        # Release the claim but keep the attempt count so exhaustion is
        # bounded; Celery retries this task and the cron re-drains 'pending'.
        with DbSession.atomic() as db:
            db.exec(
                update(OUTBOX)
                .where(OUTBOX.c.id == claimed.event_id)
                .values(state="pending", last_error=type(error).__name__[:80], lease_until=None, processed_at=func.now())
            )
        raise ExecutionDeliveryFailed(f"Execution delivery failed: event={claimed.event_id}") from error
    with DbSession.atomic() as db:
        _mark(db, claimed.event_id, "delivered")
    return True


async def drain_pending() -> int:
    count = 0
    while await drain_one():
        count += 1
    return count


def reconcile(project_uid: str) -> int:
    """Manual recovery: retry committed snapshots whose delivery did not finish."""
    project_id = InfraHelper.convert_id(project_uid)
    with DbSession.use(readonly=False) as db:
        pending_count = db.exec(
            select(func.count())
            .select_from(OUTBOX)
            .where(
                (OUTBOX.c.project_id == project_id)
                & (
                    (OUTBOX.c.state == "failed")
                    | (
                        (OUTBOX.c.state == "blocked")
                        & OUTBOX.c.payload_json.is_not(None)
                        & OUTBOX.c.last_error.not_in(PERMANENT_BLOCKS)
                    )
                )
            )
        ).first()
        db.exec(
            update(OUTBOX)
            .where(
                (OUTBOX.c.project_id == project_id)
                & (
                    (OUTBOX.c.state == "failed")
                    | (
                        (OUTBOX.c.state == "blocked")
                        & OUTBOX.c.payload_json.is_not(None)
                        & OUTBOX.c.last_error.not_in(PERMANENT_BLOCKS)
                    )
                )
            )
            .values(state="pending", last_error=None, processed_at=None, lease_until=None, attempt_count=0)
        )
    return int((pending_count[0] if isinstance(pending_count, tuple) else pending_count) or 0)


def diagnose(project_uid: str) -> list[tuple[str, str | None, int]]:
    """Return safe per-state counts and error codes without payloads or secrets."""
    project_id = InfraHelper.convert_id(project_uid)
    with DbSession.use(readonly=True) as db:
        return db.exec(
            select(OUTBOX.c.state, OUTBOX.c.last_error, func.count())
            .where(OUTBOX.c.project_id == project_id)
            .group_by(OUTBOX.c.state, OUTBOX.c.last_error)
            .order_by(OUTBOX.c.state, OUTBOX.c.last_error)
        ).all()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["drain", "reconcile", "diagnose"])
    parser.add_argument("project_uid", nargs="?")
    args = parser.parse_args()
    if args.command == "drain":
        print(f"processed={run_async(drain_pending())}")
    elif args.command == "diagnose":
        if not args.project_uid:
            parser.error("diagnose requires project_uid")
        for state, error, count in diagnose(args.project_uid):
            print(f"state={state} error={error or '-'} count={count}")
    else:
        if not args.project_uid:
            parser.error("reconcile requires project_uid")
        print(f"rechecked={reconcile(args.project_uid)}")


if __name__ == "__main__":
    main()
