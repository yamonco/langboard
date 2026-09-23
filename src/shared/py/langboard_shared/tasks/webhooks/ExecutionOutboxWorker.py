"""Wake on PostgreSQL NOTIFY and forward committed work.ready rows to Celery."""

import argparse
import logging
from datetime import timezone
from time import sleep
from uuid import UUID
import psycopg
from sqlalchemy import column, func, select, table, update
from ...core.db import DbSession
from ...core.db.DbEngine import DbEngine
from ...core.types import SnowflakeID
from ...domain.models import Card
from ...helpers import InfraHelper
from .ExecutionBindingPolicy import binding_for_project, binding_invalid_reasons
from .utils import WebhookModel
from .WebhookTask import webhook_task


logger = logging.getLogger(__name__)
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
        "direct_blocker_uids": snapshot["direct_blocker_uids"],
        "card_url": f"/board/{project_uid}/{card_uid}",
        "source_revision": snapshot["source_revision"],
    }


def drain_one() -> bool:
    """Claim one committed row; a crash can replay it, so consumers dedupe by generation."""
    with DbSession.atomic() as db:
        row = db.exec(
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
        ).first()
        if row is None:
            return False
        event_id, project_id, card_id, generation, occurred_at, event_type, snapshot = row
        if not isinstance(snapshot, dict):
            _mark(db, event_id, "blocked", "snapshot_unavailable")
            return True
        project_uid = SnowflakeID(project_id).to_short_code()
        binding = binding_for_project(project_uid)
        reasons = binding_invalid_reasons(binding, event_type)
        if reasons:
            _mark(db, event_id, "blocked", ",".join(reasons)[:80])
            return True
        model = WebhookModel(
            event=event_type,
            event_id=str(event_id),
            occurred_at=occurred_at.astimezone(timezone.utc).isoformat(),
            data=_event_data(project_id, card_id, generation, snapshot),
        )
        webhook_task(model)
        _mark(db, event_id, "scheduled")
        return True


def drain_pending() -> int:
    count = 0
    while drain_one():
        count += 1
    return count


def reconcile(project_uid: str) -> int:
    """Manual recovery: re-evaluate a board and retry its blocked rows."""
    project_id = InfraHelper.convert_id(project_uid)
    with DbSession.use(readonly=False) as db:
        card_ids = db.exec(select(Card.id).where(Card.column("project_id") == project_id)).all()
        for (card_id,) in card_ids:
            db.exec(select(func.execution_recheck_card(card_id)))
        db.exec(
            update(OUTBOX)
            .where(
                (OUTBOX.c.project_id == project_id)
                & (OUTBOX.c.state == "blocked")
                & OUTBOX.c.payload_json.is_not(None)
            )
            .values(state="pending", last_error=None, processed_at=None)
        )
        db.exec(select(func.pg_notify("langboard_execution_outbox", "reconcile")))
    return len(card_ids)


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


def listen_forever() -> None:
    # LISTEN is established before startup recovery, so no commit can be missed.
    dsn = DbEngine.get_main_engine().url.render_as_string(hide_password=False).replace("+psycopg", "")
    with psycopg.connect(dsn, autocommit=True) as connection:
        connection.execute("LISTEN langboard_execution_outbox")
        while True:
            try:
                drain_pending()
            except Exception as error:
                logger.exception("Outbox drain failed: %s", type(error).__name__)
                sleep(5)
            for _ in connection.notifies(timeout=30):
                break


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["listen", "drain", "reconcile", "diagnose"])
    parser.add_argument("project_uid", nargs="?")
    args = parser.parse_args()
    if args.command == "listen":
        listen_forever()
    elif args.command == "drain":
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
