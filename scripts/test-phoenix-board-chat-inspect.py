import argparse
import json
from datetime import timedelta
from pathlib import Path
from uuid import UUID
import httpx
from langboard_shared.core.db.DbEngine import DbEngine
from langboard_shared.core.security import AuthSecurity
from langboard_shared.core.types import SafeDateTime, SnowflakeID
from langboard_shared.domain.models import ChatGraphApprovalRequest, ChatHistory, GraphApprovalRequest, InternalBotRun
from langboard_shared.domain.models.InternalBotRun import InternalBotRunKind, InternalBotRunStatus
from langboard_shared.domain.services import DomainService
from sqlalchemy import func, select, update


parser = argparse.ArgumentParser()
parser.add_argument("run_id", type=UUID)
parser.add_argument("--tools", action="store_true")
parser.add_argument("--expire", action="store_true")
parser.add_argument("--expire-attachment", action="store_true")
parser.add_argument("--client-task-id")
parser.add_argument("--api-url")
args = parser.parse_args()
if sum((args.expire, args.expire_attachment)) > 1:
    parser.error("Only one recovery action can be selected")
if args.expire_attachment and not args.client_task_id:
    parser.error("--client-task-id is required for attachment recovery actions")
manifest = json.loads((Path("/app/local/socket-migration") / f"editor-access-{args.run_id}.json").read_text())
service = DomainService()
try:
    if args.expire or args.expire_attachment:
        project = service.project.get_by_id_like(manifest["project_uid"])
        owner = service.user.get_by_id_like(manifest["owner_uid"])
        if project is None or owner is None:
            raise RuntimeError("The diagnostic project or owner no longer exists")
        table = InternalBotRun.__table__
        target_status = InternalBotRunStatus.Resuming if args.expire else InternalBotRunStatus.Streaming
        with DbEngine.get_main_engine().begin() as connection:
            rows = (
                connection.execute(
                    select(table.c.id, table.c.client_task_id, table.c.status, table.c.request_payload)
                    .where(
                        (table.c.project_id == project.id)
                        & (table.c.user_id == owner.id)
                        & (table.c.kind == InternalBotRunKind.BoardChat)
                        & (table.c.status == target_status)
                    )
                    .order_by(table.c.id.desc())
                )
                .mappings()
                .all()
            )
            candidates = rows if args.expire else [row for row in rows if row["client_task_id"] == args.client_task_id]
            if len(candidates) != 1:
                raise RuntimeError(f"Expected exactly one diagnostic Board chat recovery run, found {len(candidates)}")
            run = candidates[0]
            result = connection.execute(
                update(table)
                .where((table.c.id == run["id"]) & (table.c.status == target_status))
                .values(lease_expires_at=SafeDateTime.now() - timedelta(seconds=1))
            )
            if result.rowcount != 1:
                raise RuntimeError("The diagnostic Board chat run changed before it could expire")
        run_uid = SnowflakeID(run["id"]).to_short_code()
        print(json.dumps({"expired": run_uid, "client_task_id": run["client_task_id"]}))
        raise SystemExit(0)

    project = service.project.get_by_id_like(manifest["project_uid"])
    owner = service.user.get_by_id_like(manifest["owner_uid"])
    if project is None or project.title != f"Migration editor access probe {args.run_id}":
        raise RuntimeError("The diagnostic project does not match this run")
    if owner is None or owner.email != f"editor-owner-{args.run_id}@example.invalid":
        raise RuntimeError("The diagnostic owner does not match this run")
    table = InternalBotRun.__table__
    history = ChatHistory.__table__
    approval = GraphApprovalRequest.__table__
    detail = ChatGraphApprovalRequest.__table__
    with DbEngine.get_main_engine().connect() as connection:
        rows = (
            connection.execute(
                select(
                    table.c.id,
                    table.c.user_id,
                    table.c.client_task_id,
                    table.c.status,
                    table.c.attempt,
                    table.c.output_text,
                    table.c.error_message,
                    table.c.graph_thread_id,
                    table.c.graph_session_id,
                    table.c.chat_session_id,
                    table.c.request_payload["resume"].label("decision"),
                ).where(table.c.project_id == project.id)
            )
            .mappings()
            .all()
        )
        sessions = list({row["chat_session_id"] for row in rows})
        approvals = (
            connection.execute(
                select(approval.c.id, approval.c.status, approval.c.resolved_by_user_id)
                .join(detail, detail.c.approval_request_id == approval.c.id)
                .where(detail.c.chat_session_id.in_(sessions))
            )
            .mappings()
            .all()
        )
        history_count = connection.scalar(
            select(func.count()).select_from(history).where(history.c.chat_session_id.in_(sessions))
        )
    card = service.card.get_by_id_like(manifest["card_uid"])
    if card is None:
        raise RuntimeError("The diagnostic Card no longer exists")
    print(
        json.dumps(
            {
                "runs": [dict(row) for row in rows],
                "approvals": [dict(row) for row in approvals],
                "history_count": history_count,
                "description": card.description.model_dump(mode="json"),
            },
            default=str,
        )
    )
    if args.tools:
        if not args.api_url:
            parser.error("--api-url is required with --tools")
        token = AuthSecurity.create_bot_one_time_token(int(owner.id), "read")
        headers = {AuthSecurity.API_TOKEN_HEADER: token}
        with httpx.Client(base_url=args.api_url, headers=headers, timeout=30) as client:
            response = client.get(
                "/schema/api/list", params={"api_names": "get_card_details,get_card_metadata,change_card_details"}
            )
            data = response.json()
            print(json.dumps({"schema_status": response.status_code, "schemas": data.get("schemas")}))
            response = client.get(f"/board/{project.get_uid()}/card/{manifest['card_uid']}")
            data = response.json()
            print(
                json.dumps(
                    {
                        "card_status": response.status_code,
                        "card_response_keys": list(data),
                        "card_title": data.get("card", {}).get("title"),
                        "error_code": data.get("code"),
                    }
                )
            )
            response = client.post(
                "/api/comfort/card_lookup",
                json={"query": {"project_uid": project.get_uid(), "card_uid": manifest["card_uid"]}},
            )
            print(json.dumps({"comfort_status": response.status_code, "comfort_result": response.json()}))
finally:
    service.close()
