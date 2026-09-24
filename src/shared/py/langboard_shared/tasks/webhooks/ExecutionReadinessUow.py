"""Evaluate work readiness at the application write transaction boundary."""

from contextlib import contextmanager
from datetime import datetime, timezone
from json import dumps
from typing import Iterator, NamedTuple
from uuid import uuid4
from sqlalchemy import select, text
from ...core.db import DbSession


WORK_EVENT = "io.langboard.work.ready.v1"

_READY_EXPRESSION = """
    EXISTS (
        SELECT 1 FROM card c
        JOIN project_execution_binding b ON b.project_id = c.project_id
        JOIN project_column target ON target.id = c.project_column_id
        JOIN webhook_setting w ON w.id = b.webhook_id
        WHERE c.id = :card_id AND b.is_enabled
          AND b.prerequisite_relationship_type_id IS NOT NULL
          AND b.events::jsonb ? 'io.langboard.work.ready.v1'
          AND w.secret_id IS NOT NULL
          AND w.events::jsonb ? 'io.langboard.work.ready.v1'
          AND c.deleted_at IS NULL AND c.archived_at IS NULL AND c.source_type IS NULL
          AND b.column_semantic_ids ->> (c.project_column_id::text) = 'ready'
          AND target.deleted_at IS NULL AND NOT target.is_archive
          AND NOT EXISTS (
              SELECT 1 FROM card_relationship r
              LEFT JOIN card prerequisite ON prerequisite.id = r.card_id_parent
              WHERE r.card_id_child = c.id
                AND r.relationship_type_id = b.prerequisite_relationship_type_id
                AND (
                    prerequisite.id IS NULL OR prerequisite.deleted_at IS NOT NULL
                    OR prerequisite.archived_at IS NOT NULL
                    OR b.column_semantic_ids ->> (prerequisite.project_column_id::text)
                       IS DISTINCT FROM 'terminal'
                )
          )
    )
"""
_READY = select(text(_READY_EXPRESSION))


class CurrentExecution(NamedTuple):
    """One point-read projection of a card's execution state and content.

    The event payload is only a "this generation is executable" signal, so the
    delivery fence is `is_ready and generation`. Mutable content (title,
    labels, assignees) is re-read here at delivery time instead of being
    replayed from the commit-time snapshot; `revision` is provenance.
    """

    revision: datetime
    is_ready: bool
    generation: int
    title: str | None
    labels: list[str]
    assignee_ids: list[int]


_LABELS_EXPRESSION = """
    COALESCE((
        SELECT jsonb_agg(label.name ORDER BY label.name)
        FROM card_assigned_project_label assigned
        JOIN project_label label ON label.id = assigned.project_label_id
        WHERE assigned.card_id = c.id
    ), '[]'::jsonb)
"""
_ASSIGNEES_EXPRESSION = """
    COALESCE((
        SELECT jsonb_agg(assigned.user_id ORDER BY assigned.user_id)
        FROM card_assigned_user assigned WHERE assigned.card_id = c.id
    ), '[]'::jsonb)
"""


def _scalar(db: DbSession, statement, **params):
    row = db.exec(statement, params=params).first()
    return row[0] if isinstance(row, tuple) else row


def current_execution(card_id: int, db: DbSession | None = None) -> CurrentExecution | None:
    """Read execution fence and current content from one database statement."""
    def read(session: DbSession):
        return session.exec(
            select(
                text("c.updated_at"),
                text("c.title"),
                text(_LABELS_EXPRESSION),
                text(_ASSIGNEES_EXPRESSION),
                text(_READY_EXPRESSION),
                text("COALESCE(g.execution_generation, 0)"),
            )
            .select_from(text("card c LEFT JOIN card_execution_generation g ON g.card_id = c.id"))
            .where(text("c.id = :card_id")),
            params={"card_id": int(card_id)},
        ).first()

    if db is None:
        # A lagging read replica could incorrectly discard a just-committed event.
        with DbSession.use(readonly=False) as primary:
            row = read(primary)
    else:
        row = read(db)
    if row is None:
        return None
    revision, title, labels, assignee_ids, ready, generation = row
    return CurrentExecution(
        revision=revision,
        is_ready=bool(ready),
        generation=int(generation),
        title=title,
        labels=[str(name) for name in labels],
        assignee_ids=[int(user_id) for user_id in assignee_ids],
    )


class ExecutionReadinessUow:
    def __init__(self, db: DbSession):
        self.db = db
        self.before: dict[int, bool] = {}

    def watch(self, card_ids) -> None:
        for card_id in sorted(set(int(card_id) for card_id in card_ids if card_id is not None)):
            if card_id in self.before:
                continue
            # Every execution-relevant writer takes the same card lock before
            # reading readiness, so concurrent transitions cannot both emit.
            self.db.exec(
                select(
                    text("pg_advisory_xact_lock(hashtextextended('langboard_execution:' || CAST(:card_id AS text), 0))")
                ),
                params={"card_id": card_id},
            )
            self.before[card_id] = bool(_scalar(self.db, _READY, card_id=card_id))

    def watch_new(self, card_id: int) -> None:
        self.db.exec(
            select(
                text("pg_advisory_xact_lock(hashtextextended('langboard_execution:' || CAST(:card_id AS text), 0))")
            ),
            params={"card_id": int(card_id)},
        )
        self.before[int(card_id)] = False

    def watch_card_and_dependents(self, card_id: int) -> None:
        rows = self.db.exec(
            select(text("card_id_child"))
            .select_from(text("card_relationship"))
            .where(text("card_id_parent = :card_id")),
            params={"card_id": int(card_id)},
        ).all()
        self.watch([card_id, *(row[0] for row in rows)])

    def watch_project(self, project_id: int) -> None:
        rows = self.db.exec(
            select(text("id")).select_from(text("card")).where(text("project_id = :project_id")),
            params={"project_id": project_id},
        ).all()
        self.watch(row[0] for row in rows)

    def watch_webhook(self, webhook_id: int) -> None:
        rows = self.db.exec(
            select(text("project_id"))
            .select_from(text("project_execution_binding"))
            .where(text("webhook_id = :webhook_id")),
            params={"webhook_id": int(webhook_id)},
        ).all()
        for (project_id,) in rows:
            self.watch_project(project_id)

    def finish(self) -> None:
        for card_id, was_ready in self.before.items():
            now_ready = bool(_scalar(self.db, _READY, card_id=card_id))
            if was_ready and not now_ready:
                self.db.exec(
                    text("""
                        UPDATE execution_outbox SET state = 'superseded', last_error = 'readiness_revoked'
                        WHERE card_id = :card_id AND state = 'pending'
                    """),
                    params={"card_id": card_id},
                )
                continue
            if was_ready or not now_ready:
                continue
            self.db.exec(
                text("""
                    INSERT INTO card_execution_generation(card_id, execution_generation)
                    VALUES (:card_id, 1)
                    ON CONFLICT (card_id) DO UPDATE SET
                        execution_generation = card_execution_generation.execution_generation + 1
                """),
                params={"card_id": card_id},
            )
            generation = _scalar(
                self.db,
                select(text("execution_generation"))
                .select_from(text("card_execution_generation"))
                .where(text("card_id = :card_id")),
                card_id=card_id,
            )
            snapshot = self.db.exec(
                select(
                    text("""
                    c.project_id, c.title, c.updated_at,
                    b.id, b.updated_at, b.webhook_uid,
                        COALESCE((SELECT jsonb_agg(label.name ORDER BY label.name)
                            FROM card_assigned_project_label assigned
                            JOIN project_label label ON label.id = assigned.project_label_id
                            WHERE assigned.card_id = c.id), '[]'::jsonb),
                        COALESCE((SELECT jsonb_agg(assigned.user_id ORDER BY assigned.user_id)
                            FROM card_assigned_user assigned WHERE assigned.card_id = c.id), '[]'::jsonb)
                """)
                )
                .select_from(text("card c JOIN project_execution_binding b ON b.project_id = c.project_id"))
                .where(text("c.id = :card_id")),
                params={"card_id": card_id},
            ).first()
            project_id, title, revision, binding_id, binding_revision, webhook_uid, labels, assignee_ids = snapshot
            event_id = uuid4()
            self.db.exec(
                text("""
                    INSERT INTO execution_outbox(
                        id, project_id, card_id, execution_generation, occurred_at,
                        event_type, payload_json
                    ) VALUES (
                        :event_id, :project_id, :card_id, :generation, :occurred_at,
                        :event_type, CAST(:payload_json AS jsonb)
                    )
                """),
                params={
                    "event_id": event_id,
                    "project_id": project_id,
                    "card_id": card_id,
                    "generation": generation,
                    "occurred_at": datetime.now(timezone.utc),
                    "event_type": WORK_EVENT,
                    "payload_json": dumps(
                        {
                            "title": title,
                            "labels": labels,
                            "assignee_ids": assignee_ids,
                            "source_revision": revision.isoformat(),
                            "binding_id": str(binding_id),
                            "binding_revision": binding_revision.isoformat(),
                            "webhook_uid": webhook_uid,
                        }
                    ),
                },
            )
            def enqueue(event_id=event_id) -> None:
                from .ExecutionOutboxTask import execution_outbox_task

                execution_outbox_task(str(event_id))

            self.db.after_commit(enqueue)


@contextmanager
def execution_readiness_uow() -> Iterator[ExecutionReadinessUow]:
    with DbSession.atomic() as db:
        uow = ExecutionReadinessUow(db)
        yield uow
        uow.finish()
