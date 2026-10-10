"""Native FastMCP dispatch rechecks actual DB roles before plan owner entry."""

from types import SimpleNamespace
from unittest.mock import Mock
from fastmcp import Client
from langboard.mcp_integration.Server import McpServer
from langboard.mcp_integration.Tool import McpTool
from langboard.mcp_tools import ExecutionMcp
from langboard.middlewares.McpAuthMiddleware import mcp_auth_context
from langboard_shared.core.db import DbSession
from langboard_shared.core.db.DbEngine import DbEngine
from langboard_shared.core.security.CollaborationChannel import CollaborationChannel
from langboard_shared.domain.models import Project, ProjectRole, User
from sqlalchemy import create_engine, update


async def test_actual_roles_gate_native_review_and_revoked_replay(monkeypatch):
    import importlib

    server_module = importlib.import_module("langboard.mcp_integration.Server")
    engine = create_engine("sqlite://")
    Project.__table__.create(engine)
    ProjectRole.__table__.create(engine)
    project = Project(id=100, owner_id=999, title="QA")
    actor = User(id=200, firstname="QA", lastname="User", email="qa@example.invalid", password="unused", is_admin=False)
    role = ProjectRole(id=300, project_id=100, user_id=200, actions=["read"])
    with engine.begin() as conn:
        conn.execute(Project.__table__.insert(), {name: getattr(project, name) for name in Project.model_fields})
        conn.execute(ProjectRole.__table__.insert(), {name: getattr(role, name) for name in ProjectRole.model_fields})
    monkeypatch.setattr(DbEngine, "get_main_engine", lambda: engine)
    monkeypatch.setattr(DbEngine, "get_readonly_engine", lambda: engine)
    command = Mock(
        return_value={"receipt": {"status": "review_ready"}, "created": True, "generation": 5, "moved_to_review": False}
    )
    history = Mock(return_value={"receipts": []})
    monkeypatch.setattr(ExecutionMcp, "store_execution_receipt", command)
    monkeypatch.setattr(ExecutionMcp, "read_execution_receipts", history)
    monkeypatch.setattr(server_module, "DomainService", lambda: SimpleNamespace(close=lambda: None))
    inject = McpServer._inject_kwargs

    def inject_test_service(name, param, auth_value, kwargs):
        if getattr(param.annotation, "__name__", None) == "DomainService":
            kwargs[name] = SimpleNamespace(close=lambda: None)
            return kwargs, None
        return inject(name, param, auth_value, kwargs)

    monkeypatch.setattr(McpServer, "_inject_kwargs", inject_test_service)
    names = ("get_card_execution_receipts", "submit_card_execution_review")
    metadata = {name: McpTool.get_tool(name) for name in names}
    monkeypatch.setattr(McpTool, "get_tools", lambda: metadata)
    monkeypatch.setattr(McpTool, "get_tool", lambda name: metadata.get(name))
    _, server = McpServer.get_http_app("agent")
    token = mcp_auth_context.set(
        {"user_or_bot": actor, "tool_group": SimpleNamespace(activated_at=object(), tools=list(names))}
    )
    args = {"project_uid": project.get_uid(), "card_uid": "card"}
    apply_args = {
        **args,
        "generation": 5,
        "idempotency_key": f"langboard:{project.get_uid()}:card:5:receipt",
        "occurred_at": "2026-10-05T00:00:00Z",
        "report": {
            "changed": "Native command",
            "verified": "Role checks",
            "remaining": "Human review",
            "evidence_refs": ["https://example.invalid/run/1"],
        },
    }
    try:
        async with Client(server) as client:
            assert not (await client.call_tool(names[0], args, raise_on_error=False)).is_error
            history.assert_called_once()
            assert history.call_args.args == (project.get_uid(), "card", actor, CollaborationChannel.Mcp)
            denied = await client.call_tool(names[1], apply_args, raise_on_error=False)
            assert denied.is_error
            command.assert_not_called()
            with DbSession.atomic() as db:
                db.exec(
                    update(ProjectRole)
                    .where(ProjectRole.column("id") == role.id)
                    .values(actions=["read", "card_update"])
                )
            allowed = await client.call_tool(names[1], apply_args, raise_on_error=False)
            assert not allowed.is_error
            assert command.call_count == 1
            assert command.call_args.kwargs == {"channel": CollaborationChannel.Mcp}
            saved_form = command.call_args.args[3]
            assert saved_form.status == "review_ready"
            assert saved_form.review.remaining == "Human review"
            assert saved_form.evidence[0].refs == ["https://example.invalid/run/1"]
            for invalid in (
                {"generation": 0},
                {"occurred_at": "2026-10-05T00:00:00"},
                {"report": {"changed": "x", "verified": "x", "remaining": "x", "evidence_refs": []}},
            ):
                rejected = await client.call_tool(names[1], {**apply_args, **invalid}, raise_on_error=False)
                assert rejected.is_error
            assert command.call_count == 1
            with DbSession.atomic() as db:
                db.exec(update(ProjectRole).where(ProjectRole.column("id") == role.id).values(actions=["read"]))
            revoked = await client.call_tool(names[1], apply_args, raise_on_error=False)
            assert revoked.is_error
            assert command.call_count == 1
            # Other projects cannot use a valid role on this board.
            other = await client.call_tool(
                names[0], {**args, "project_uid": Project(id=101, title="Other").get_uid()}, raise_on_error=False
            )
            assert other.is_error
            assert history.call_count == 1
    finally:
        mcp_auth_context.reset(token)
        engine.dispose()
