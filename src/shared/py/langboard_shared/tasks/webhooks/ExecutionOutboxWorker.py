"""Drain committed work.ready rows into the existing Celery delivery path."""

import argparse
from datetime import timezone
from uuid import UUID
from sqlalchemy import column, func, select, table, update
from ...core.db import DbSession
from ...core.types import SnowflakeID
from ...helpers import InfraHelper
from .ExecutionBindingPolicy import binding_for_project, binding_invalid_reasons
from .ExecutionReadinessUow import current_execution
from .utils import WebhookModel
from .WebhookTask import webhook_delivery_task


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
)
PERMANENT_BLOCKS = ("snapshot_unavailable", "destination_unavailable", "stale_binding")


def _mark(db: DbSession, event_id: UUID, state: str, error: str | None = None) -> None:
    db.exec(
        update(OUTBOX).where(OUTBOX.c.id == event_id).values(state=state, last_error=error, processed_at=func.now())
    )


def _event_data(project_id: int, card_id: int, generation: int, snapshot: dict) -> dict:
    """Only deterministic ID projection; mutable Card data was frozen at commit."""
    project_uid = SnowflakeID(project_id).to_short_code()
    card_uid = SnowflakeID(card_id).to_short_code()
    return {
        "project_uid": project_uid,
        "card_uid": card_uid,
        "execution_generation": generation,
        "title": snapshot["title"],
        "labels": snapshot["labels"],
        "assignees": [SnowflakeID(uid).to_short_code() for uid in snapshot["assignee_ids"]],
        "card_url": f"/board/{project_uid}/{card_uid}",
        "source_revision": snapshot["source_revision"],
    }


def drain_one(event_id: UUID | None = None) -> bool:
    """Claim one committed row; a crash can replay it, so consumers dedupe by generation."""
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
            )
            .where(OUTBOX.c.state == "pending")
            .order_by(OUTBOX.c.occurred_at)
            .limit(1)
            .with_for_update(skip_locked=True)
        )
        if event_id is not None:
            query = query.where(OUTBOX.c.id == event_id)
        row = db.exec(query).first()
        if row is None:
            return False
        event_id, project_id, card_id, generation, occurred_at, event_type, snapshot = row
        if not isinstance(snapshot, dict):
            _mark(db, event_id, "blocked", "snapshot_unavailable")
            return True
        if not all(snapshot.get(key) for key in ("binding_id", "binding_revision", "webhook_uid")):
            _mark(db, event_id, "blocked", "destination_unavailable")
            return True
        current = current_execution(card_id, db)
        if (
            current is None
            or not current[1]
            or current[2] != generation
            or current[0].isoformat() != snapshot.get("source_revision")
        ):
            _mark(db, event_id, "superseded", "stale_readiness")
            return True
        project_uid = SnowflakeID(project_id).to_short_code()
        binding = binding_for_project(project_uid)
        reasons = binding_invalid_reasons(binding, event_type)
        if reasons:
            _mark(db, event_id, "blocked", ",".join(reasons)[:80])
            return True
        if (
            str(binding.id) != snapshot["binding_id"]
            or binding.updated_at.isoformat() != snapshot["binding_revision"]
            or binding.webhook_uid != snapshot["webhook_uid"]
        ):
            _mark(db, event_id, "blocked", "stale_binding")
            return True
        model = WebhookModel(
            event=event_type,
            event_id=str(event_id),
            occurred_at=occurred_at.astimezone(timezone.utc).isoformat(),
            data=_event_data(project_id, card_id, generation, snapshot),
        )
        webhook_delivery_task(
            model,
            snapshot["webhook_uid"],
            snapshot["binding_id"],
            snapshot["binding_revision"],
        )
        _mark(db, event_id, "scheduled")
        return True


def drain_pending() -> int:
    count = 0
    while drain_one():
        count += 1
    return count


def reconcile(project_uid: str) -> int:
    """Manual recovery: retry committed snapshots that had a blocked delivery."""
    project_id = InfraHelper.convert_id(project_uid)
    with DbSession.use(readonly=False) as db:
        pending_count = db.exec(
            select(func.count())
            .select_from(OUTBOX)
            .where(
                (OUTBOX.c.project_id == project_id)
                & (OUTBOX.c.state == "blocked")
                & OUTBOX.c.payload_json.is_not(None)
                & OUTBOX.c.last_error.not_in(PERMANENT_BLOCKS)
            )
        ).first()
        db.exec(
            update(OUTBOX)
            .where(
                (OUTBOX.c.project_id == project_id)
                & (OUTBOX.c.state == "blocked")
                & OUTBOX.c.payload_json.is_not(None)
                & OUTBOX.c.last_error.not_in(PERMANENT_BLOCKS)
            )
            .values(state="pending", last_error=None, processed_at=None)
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
        print(f"processed={drain_pending()}")
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
