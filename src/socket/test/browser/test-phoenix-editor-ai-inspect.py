import argparse
import json
from collections.abc import Sequence
from datetime import timedelta
from pathlib import Path
from uuid import UUID
from langboard_shared.core.db import EditorContentModel
from langboard_shared.core.db.DbEngine import DbEngine
from langboard_shared.core.types import SafeDateTime, SnowflakeID
from langboard_shared.domain.models import (
    Card,
    EditorGraphApprovalRequest,
    GraphApprovalRequest,
    InternalBotRun,
)
from langboard_shared.domain.models.GraphApprovalRequest import GraphApprovalOriginType
from langboard_shared.domain.models.InternalBotRun import InternalBotRunKind, InternalBotRunStatus
from langboard_shared.domain.services import DomainService
from sqlalchemy import select, update
from sqlalchemy.engine import RowMapping


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("run_id", type=UUID)
    parser.add_argument("--cancel-pending", action="store_true")
    parser.add_argument("--expire", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    manifest_path = Path("/app/local/socket-migration") / f"editor-access-{args.run_id}.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    project_id = SnowflakeID.from_short_code(manifest["project_uid"])
    card_id = SnowflakeID.from_short_code(manifest["card_uid"])
    runs = InternalBotRun.__table__
    approvals = GraphApprovalRequest.__table__
    editors = EditorGraphApprovalRequest.__table__
    cards = Card.__table__

    with DbEngine.get_main_engine().connect() as connection:
        records = (
            connection.execute(
                select(
                    runs.c.id,
                    runs.c.client_task_id,
                    runs.c.kind,
                    runs.c.status,
                    runs.c.attempt,
                    runs.c.graph_thread_id,
                    runs.c.output_text,
                    runs.c.error_message,
                    runs.c.request_payload["resume"].label("decision"),
                ).where(runs.c.project_id == project_id)
            )
            .mappings()
            .all()
        )
        decisions = (
            connection.execute(
                select(
                    approvals.c.id,
                    approvals.c.thread_id,
                    approvals.c.status,
                    approvals.c.resolved_by_user_id,
                )
                .join(editors, editors.c.approval_request_id == approvals.c.id)
                .where((editors.c.scope_table == "card") & (editors.c.scope_id == card_id))
            )
            .mappings()
            .all()
        )
        description = connection.scalar(select(cards.c.description).where(cards.c.id == card_id))

    if args.expire:
        expire_resuming_run(project_id, records)
        return

    if not isinstance(description, EditorContentModel):
        raise RuntimeError("The synthetic Card description is unavailable")

    if args.cancel_pending:
        cancel_pending(args.run_id, manifest, records)
        print(json.dumps({"pending_runs_cancelled": True}))
        return

    print(
        json.dumps(
            {
                "runs": [dict(row) for row in records],
                "approvals": [dict(row) for row in decisions],
                "description": description.model_dump(),
            },
            default=str,
        )
    )


def expire_resuming_run(project_id: SnowflakeID, records: Sequence[RowMapping]) -> None:
    candidates = [
        record
        for record in records
        if record["kind"] == InternalBotRunKind.EditorChat and record["status"] == InternalBotRunStatus.Resuming
    ]
    if len(candidates) != 1:
        raise RuntimeError(f"Expected exactly one diagnostic Editor run to expire, found {len(candidates)}")

    run = candidates[0]
    table = InternalBotRun.__table__
    with DbEngine.get_main_engine().begin() as connection:
        result = connection.execute(
            update(table)
            .where(
                (table.c.id == run["id"])
                & (table.c.project_id == project_id)
                & (table.c.status == InternalBotRunStatus.Resuming)
            )
            .values(lease_expires_at=SafeDateTime.now() - timedelta(seconds=1))
        )
        if result.rowcount != 1:
            raise RuntimeError("The diagnostic Editor run changed before it could expire")

    print(json.dumps({"expired": str(run["id"]), "client_task_id": str(run["client_task_id"])}))


def cancel_pending(run_id: UUID, manifest: dict[str, str], records: Sequence[RowMapping]) -> None:
    with DomainService.use() as service:
        project = service.project.get_by_id_like(manifest["project_uid"])
        owner = service.user.get_by_id_like(manifest["owner_uid"])
        if project is None or project.title != f"Migration editor access probe {run_id}":
            raise RuntimeError("The synthetic project does not match this run")
        if owner is None or owner.email != f"editor-owner-{run_id}@example.invalid":
            raise RuntimeError("The synthetic owner does not match this run")

        pending_statuses = {
            InternalBotRunStatus.Accepted,
            InternalBotRunStatus.Streaming,
            InternalBotRunStatus.AwaitingApproval,
        }
        for record in records:
            if record["status"] in pending_statuses:
                kind = record["kind"]
                if not isinstance(kind, InternalBotRunKind):
                    raise RuntimeError("The synthetic Editor run kind is invalid")
                service.internal_bot_run.cancel_editor(
                    kind,
                    UUID(str(record["client_task_id"])),
                    owner.id,
                    project.id,
                )
        service.graph_approval_request.cancel_pending_by_scope(
            project,
            "card",
            manifest["card_uid"],
            reason="Synthetic editor probe cleanup",
            origin_type=GraphApprovalOriginType.Editor,
        )


if __name__ == "__main__":
    main()
