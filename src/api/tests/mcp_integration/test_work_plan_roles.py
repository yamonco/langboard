"""Native FastMCP dispatch rechecks actual DB roles before plan owner entry."""

from types import SimpleNamespace
from unittest.mock import Mock
from fastmcp import Client
from langboard.card_workspace.application.work_plan import WorkPlan
from langboard.mcp_integration.Server import McpServer
from langboard.mcp_integration.Tool import McpTool
from langboard.mcp_tools import CardMcp
from langboard.middlewares.McpAuthMiddleware import mcp_auth_context
from langboard_shared.core.db import DbSession
from langboard_shared.core.db.DbEngine import DbEngine
from langboard_shared.domain.models import Project, ProjectRole, User
from sqlalchemy import create_engine, update


async def test_actual_db_roles_block_apply_and_revoked_replay(monkeypatch):
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
    plan = WorkPlan(
        project_uid=project.get_uid(),
        anchor_card_uid="anchor",
        new_checklists=[{"target_card_ref": "anchor", "title": "Steps", "items": ["Verify"]}],
    )
    owner = Mock()
    owner.preview.return_value = {
        "revision": "a" * 64,
        "plan": plan.model_dump(mode="json"),
        "counts": {"cards": 0, "cardifications": 0, "checklists": 1},
    }
    owner.apply.return_value = {
        "graph": None,
        "cardifications": [],
        "checklists": [],
        "applied_revision": "a" * 64,
        "all_succeeded": True,
        "replayed": False,
    }
    constructor = Mock(return_value=owner)
    monkeypatch.setattr(CardMcp, "WorkPlanService", constructor)
    monkeypatch.setattr(server_module, "DomainService", lambda: SimpleNamespace(close=lambda: None))
    inject = McpServer._inject_kwargs

    def inject_test_service(name, param, auth_value, kwargs):
        if getattr(param.annotation, "__name__", None) == "DomainService":
            kwargs[name] = SimpleNamespace(close=lambda: None)
            return kwargs, None
        return inject(name, param, auth_value, kwargs)

    monkeypatch.setattr(McpServer, "_inject_kwargs", inject_test_service)
    names = ("preview_card_work_plan", "apply_card_work_plan")
    metadata = {name: McpTool.get_tool(name) for name in names}
    monkeypatch.setattr(McpTool, "get_tools", lambda: metadata)
    monkeypatch.setattr(McpTool, "get_tool", lambda name: metadata.get(name))
    _, server = McpServer.get_http_app("agent")
    token = mcp_auth_context.set(
        {"user_or_bot": actor, "tool_group": SimpleNamespace(activated_at=object(), tools=list(names))}
    )
    args = {"project_uid": project.get_uid(), "plan": plan.model_dump(mode="json")}
    apply_args = {**args, "expected_revision": "a" * 64, "request_id": "stable-request"}
    try:
        async with Client(server) as client:
            assert not (await client.call_tool(names[0], args, raise_on_error=False)).is_error
            owner.preview.assert_called_once()
            denied = await client.call_tool(names[1], apply_args, raise_on_error=False)
            assert denied.is_error
            owner.apply.assert_not_called()
            with DbSession.atomic() as db:
                db.exec(
                    update(ProjectRole)
                    .where(ProjectRole.column("id") == role.id)
                    .values(actions=["read", "card_update"])
                )
            allowed = await client.call_tool(names[1], apply_args, raise_on_error=False)
            assert not allowed.is_error
            assert owner.apply.call_count == 1
            with DbSession.atomic() as db:
                db.exec(update(ProjectRole).where(ProjectRole.column("id") == role.id).values(actions=["read"]))
            revoked = await client.call_tool(names[1], apply_args, raise_on_error=False)
            assert revoked.is_error
            assert owner.apply.call_count == 1
            # Other projects cannot use a valid role on this board.
            other = await client.call_tool(
                names[0], {**args, "project_uid": Project(id=101, title="Other").get_uid()}, raise_on_error=False
            )
            assert other.is_error
            assert owner.preview.call_count == 1
    finally:
        mcp_auth_context.reset(token)
        engine.dispose()
