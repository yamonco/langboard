# ruff: noqa: F811
"""Per-reference audit pages preserve current authority without touching secrets."""

import json
import pytest
from langboard_shared.core.db import DbSession
from langboard_shared.core.security import KeyVault
from langboard_shared.domain.services.factory.SecretReferenceService import SecretReferenceUnavailable
from langboard_shared.domain.services.factory.SecretReferenceService_test import secrets  # noqa: F401
from langboard_shared.domain.services.factory.WorkflowStageService_app_test import board  # noqa: F401
from pydantic import SecretStr


def test_history_pages_no_material_with_revision_facts_and_foreign_cursor_denial(secrets, monkeypatch):
    service, board, _ = secrets
    actor = board[1]
    reference = service.create(actor, "personal", "me", "history/key", SecretStr("fixture-sensitive"))
    service.resolve_for_runtime(actor, reference["uri"])
    renamed = service.rename(actor, reference["uri"], "history/renamed", 0)
    rotated = service.rotate(actor, reference["uri"], SecretStr("replacement-sensitive"), renamed["revision"])
    other = service.create(actor, "personal", "me", "history/other", SecretStr("other-sensitive"))
    monkeypatch.setattr(KeyVault, "get_key", lambda *_: pytest.fail("History read vault material"))
    monkeypatch.setattr(KeyVault, "store_secret", lambda *_: pytest.fail("History wrote vault material"))
    first = service.list_audit(actor, reference["uri"], limit=2)
    assert [row["action"] for row in first["items"]] == ["rotated", "renamed"]
    assert [(row["revision_before"], row["revision_after"]) for row in first["items"]] == [(1, 2), (0, 1)]
    second = service.list_audit(actor, reference["uri"], limit=2, cursor=first["next_cursor"])
    assert [row["action"] for row in second["items"]] == ["resolved", "created"]
    assert second["items"][0]["revision_before"] == 0 and second["items"][1]["revision_before"] is None
    assert second["next_cursor"] is None
    assert not set(row["uid"] for row in first["items"]) & set(row["uid"] for row in second["items"])
    assert not any(
        word in json.dumps([first, second]) for word in ["sensitive", "locator", "provider", "source_uid", "scope_id"]
    )
    foreign_cursor = service.list_audit(actor, other["uri"])["items"][0]["uid"]
    with pytest.raises(SecretReferenceUnavailable):
        service.list_audit(actor, reference["uri"], cursor=foreign_cursor)
    assert rotated["revision"] == 2
    with DbSession.use(readonly=False) as db:
        actor.activated_at = None
        db.update(actor)
    with pytest.raises(SecretReferenceUnavailable):
        service.list_audit(actor, reference["uri"], cursor=first["next_cursor"])


def test_history_rechecks_moved_reference_and_role_before_next_page(secrets):
    service, board, _ = secrets
    actor = board[1]
    with DbSession.use(readonly=False) as db:
        board[4].actions = ["read", "update"]
        db.update(board[4])
    reference = service.create(actor, "project", board[2].get_uid(), "history/board", SecretStr("fixture-sensitive"))
    service.resolve_for_runtime(actor, reference["uri"])
    first = service.list_audit(actor, reference["uri"], limit=1)
    with DbSession.use(readonly=False) as db:
        board[4].actions = ["read"]
        db.update(board[4])
    with pytest.raises(SecretReferenceUnavailable):
        service.list_audit(actor, reference["uri"], cursor=first["next_cursor"])
    with pytest.raises(SecretReferenceUnavailable):
        service.list_audit(board[3], reference["uri"])
    with pytest.raises(ValueError):
        service.list_audit(actor, reference["uri"], limit=51)


@pytest.mark.parametrize("board", ["sqlite-http", "postgresql-test"], indirect=True)
def test_native_authenticated_history_http_and_current_revocation(secrets, monkeypatch):
    import importlib
    from types import SimpleNamespace
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from langboard.middlewares.ApiAuthMiddleware import ApiAuthMiddleware
    from langboard.routes.account.SecretReferenceApi import get_secret_reference_history
    from langboard_shared.core.db.DbEngine import DbEngine
    from langboard_shared.core.routing import AppRouter
    from langboard_shared.core.security import AuthSecurity
    from langboard_shared.Env import Env

    service, board, _ = secrets
    actor = board[1]
    meta = service.create(actor, "personal", "me", "history/http", SecretStr("fixture-sensitive"))
    wrapper = SimpleNamespace(secret_reference=service, close=lambda: None)
    monkeypatch.setattr(DbEngine, "get_readonly_engine", DbEngine.get_main_engine)
    monkeypatch.setattr(
        importlib.import_module("langboard.middlewares.ApiAuthMiddleware"), "DomainService", lambda: wrapper
    )
    app = FastAPI()
    app.include_router(AppRouter.api)
    for route in app.routes:
        if getattr(route, "endpoint", None) is get_secret_reference_history:
            for dependency in route.dependant.dependencies:
                if dependency.name == "service":
                    app.dependency_overrides[dependency.call] = lambda: wrapper
    app.add_middleware(ApiAuthMiddleware, routes=AppRouter.api.routes)
    access, refresh = AuthSecurity.authenticate(actor.id)
    url = "/secret-references/" + meta["uri"].rsplit("/", 1)[1] + "/history"
    with TestClient(app) as client:
        assert client.get(url).status_code == 401
        client.cookies.set(Env.REFRESH_TOKEN_NAME, refresh)
        headers = {"Authorization": f"Bearer {access}"}
        response = client.get(url, headers=headers)
        assert response.status_code == 200 and response.json()["items"][0]["action"] == "created"
        assert response.headers["cache-control"] == "no-store"
        assert "fixture-sensitive" not in response.text
        with DbSession.use(readonly=False) as db:
            actor.activated_at = None
            db.update(actor)
        assert client.get(url, headers=headers).status_code in {401, 403, 404}


@pytest.mark.asyncio
async def test_fastmcp_history_schema_and_no_vault_reads(secrets, monkeypatch):
    from fastmcp import Client, FastMCP
    from langboard.mcp_integration.Extensions import create_native_extension_provider
    from langboard.mcp_integration.Server import McpServer
    from langboard.mcp_tools.SecretReferenceMcp import list_secret_reference_history
    from langboard.middlewares.McpAuthMiddleware import mcp_auth_context
    from langboard_shared.domain.services import DomainService

    service, board, _ = secrets
    actor = board[1]
    meta = service.create(actor, "personal", "me", "history/mcp", SecretStr("fixture-sensitive"))
    monkeypatch.setattr(DomainService, "secret_reference", property(lambda _: service))
    monkeypatch.setattr(KeyVault, "get_key", lambda *_: pytest.fail("MCP history resolved material"))
    server = FastMCP("secret-history")
    server.add_provider(
        create_native_extension_provider([list_secret_reference_history.__name__], McpServer._wrap_tool)
    )
    token = mcp_auth_context.set({"user_or_bot": actor})
    try:
        async with Client(server) as client:
            tool = (await client.list_tools())[0]
            assert tool.annotations.readOnlyHint
            assert set(tool.inputSchema["properties"]) == {"uri", "limit", "cursor"}
            result = (await client.call_tool(tool.name, {"uri": meta["uri"], "limit": 1})).structured_content
            assert result["items"][0]["action"] == "created"
            assert "fixture-sensitive" not in json.dumps(result)
    finally:
        mcp_auth_context.reset(token)


def test_request_correlation_and_fixed_reason_codes_never_include_material(secrets):
    from langboard_shared.domain.services.factory.SecretReferenceService import SecretAuditSource

    service, board, _ = secrets
    actor = board[1]
    source = SecretAuditSource("api", "secret_input", request_id="server-operation-123", reason_code="user_input")
    meta = service.create(actor, "personal", "me", "history/correlation", SecretStr("must-not-log"), source=source)
    service.resolve_for_runtime(actor, meta["uri"])
    events = service.list_audit(actor, meta["uri"])["items"]
    assert events[1]["request_id"] == "server-operation-123" and events[1]["reason_code"] == "user_input"
    assert events[0]["reason_code"] == "runtime_use" and len(events[0]["request_id"]) == 32
    assert "must-not-log" not in json.dumps(events)
    with pytest.raises(ValueError):
        SecretAuditSource(reason_code="free text secret value")
    with pytest.raises(ValueError):
        SecretAuditSource(request_id="invalid request with spaces")


def test_audit_correlation_migration_preserves_legacy_rows_and_guards_downgrade(secrets, monkeypatch):
    import importlib.util
    from pathlib import Path
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    from langboard_shared.core.db.DbEngine import DbEngine
    from sqlalchemy import text

    service, board, _ = secrets
    meta = service.create(board[1], "personal", "me", "history/migration", SecretStr("fixture-sensitive"))
    path = Path(__file__).resolve().parents[2] / "langboard/migrations/versions/20261008114000-e87412793ab3.py"
    spec = importlib.util.spec_from_file_location("audit_correlation_migration", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    engine = DbEngine.get_main_engine()
    with engine.begin() as connection:
        monkeypatch.setattr(migration, "op", Operations(MigrationContext.configure(connection)))
        with pytest.raises(RuntimeError, match="correlation evidence"):
            migration.downgrade()
        connection.execute(text("UPDATE secret_reference_audit SET request_id=NULL, reason_code=NULL"))
        migration.downgrade()
        migration.upgrade()
    event = service.list_audit(board[1], meta["uri"])["items"][0]
    assert event["action"] == "created"
    assert event["request_id"] is None and event["reason_code"] is None


def test_binding_audit_owns_no_material_and_rolls_back_with_destination(secrets, monkeypatch):
    from langboard_shared.domain.services.factory.SecretReferenceService import (
        SecretAuditSource,
        SecretReferenceConflict,
    )

    service, board, _ = secrets
    actor = board[1]
    meta = service.create(actor, "personal", "me", "history/binding", SecretStr("binding-sensitive"))
    source = SecretAuditSource("app_connection", "trusted_connection")
    monkeypatch.setattr(KeyVault, "get_key", lambda *_: pytest.fail("Binding audit read material"))
    monkeypatch.setattr(KeyVault, "store_secret", lambda *_: pytest.fail("Binding audit wrote material"))
    with pytest.raises(RuntimeError):
        service.audit_binding(actor, meta["uri"], 0, source=source)
    with pytest.raises(RuntimeError):
        with DbSession.atomic():
            service.audit_binding(actor, meta["uri"], 0, source=source)
            raise RuntimeError("Destination rollback")
    assert [x["action"] for x in service.list_audit(actor, meta["uri"])["items"]] == ["created"]
    with DbSession.atomic():
        with pytest.raises(SecretReferenceUnavailable):
            service.audit_binding(board[3], meta["uri"], 0, source=source)
        with pytest.raises(SecretReferenceConflict):
            service.audit_binding(actor, meta["uri"], 1, source=source)
        with pytest.raises(ValueError):
            service.audit_binding(actor, meta["uri"], 0, source=SecretAuditSource("api", "caller"))
        service.audit_binding(actor, meta["uri"], 0, source=source)
    event = service.list_audit(actor, meta["uri"])["items"][0]
    assert (event["action"], event["revision_before"], event["revision_after"], event["reason_code"]) == (
        "bound",
        0,
        0,
        "reference_bound",
    )
    assert "source_uid" not in event and "binding-sensitive" not in json.dumps(event)
    service.revoke(actor, meta["uri"], 0)
    with DbSession.atomic(), pytest.raises(SecretReferenceUnavailable):
        service.audit_binding(actor, meta["uri"], 1, source=source)


def test_binding_migration_preserves_history_and_refuses_evidence_loss(secrets, monkeypatch):
    import importlib.util
    from pathlib import Path
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    from langboard_shared.core.db.DbEngine import DbEngine
    from langboard_shared.domain.services.factory.SecretReferenceService import SecretAuditSource

    service, board, _ = secrets
    actor = board[1]
    meta = service.create(actor, "personal", "me", "history/migrate-binding", SecretStr("fixture-sensitive"))
    path = Path(__file__).resolve().parents[2] / "langboard/migrations/versions/20261009040000-7c98451eab03.py"
    spec = importlib.util.spec_from_file_location("binding_audit_migration", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    engine = DbEngine.get_main_engine()
    before = service.list_audit(actor, meta["uri"])
    with engine.begin() as connection:
        monkeypatch.setattr(migration, "op", Operations(MigrationContext.configure(connection)))
        migration.downgrade()
        migration.upgrade()
    assert service.list_audit(actor, meta["uri"]) == before
    with DbSession.atomic():
        service.audit_binding(actor, meta["uri"], 0, source=SecretAuditSource("app_connection", "connection"))
    with engine.begin() as connection:
        monkeypatch.setattr(migration, "op", Operations(MigrationContext.configure(connection)))
        with pytest.raises(RuntimeError, match="Cannot discard"):
            migration.downgrade()
    assert [x["action"] for x in service.list_audit(actor, meta["uri"])["items"]] == ["bound", "created"]


def test_card_source_links_recheck_current_acl_and_channel_without_material(secrets, monkeypatch):
    from langboard_shared.core.db.DbEngine import DbEngine
    from langboard_shared.core.security.CollaborationChannel import CollaborationChannel
    from langboard_shared.core.types import SafeDateTime
    from langboard_shared.domain import models
    from langboard_shared.domain.services import DomainService
    from langboard_shared.domain.services.factory.CardService import CardService
    from langboard_shared.domain.services.factory.SecretReferenceService import SecretAuditSource
    from langboard_shared.domain.services.factory.WorkflowStageService import WorkflowStageService

    service, board, _ = secrets
    actor, project, member, role, columns = board[1:6]
    engine = DbEngine.get_main_engine()
    required = {models.Card.__table__}
    pending = list(required)
    while pending:
        for fk in pending.pop().foreign_keys:
            if fk.column.table not in required:
                required.add(fk.column.table)
                pending.append(fk.column.table)
    models.Card.metadata.create_all(engine, tables=list(required), checkfirst=True)
    domain = DomainService()
    monkeypatch.setattr(domain.card, "_resolve_internal_access", lambda *args: False)
    monkeypatch.setattr(
        service,
        "_get_service",
        lambda cls: domain.card if cls is CardService else board[0] if cls is WorkflowStageService else None,
    )
    with DbSession.atomic() as db:
        card = models.Card(
            project_id=project.id,
            project_column_id=columns[0].id,
            title="Private source title",
            created_by_user_id=actor.id,
            visibility="SHARED",
        )
        db.insert(card)
    meta = service.create(
        actor,
        "personal",
        "me",
        "history/card-source",
        SecretStr("fixture-sensitive"),
        source=SecretAuditSource("card", card.get_uid()),
    )
    monkeypatch.setattr(KeyVault, "get_key", lambda *_: pytest.fail("Source history read material"))
    expected = {"kind": "card", "href": f"/board/{project.get_uid()}/{card.get_uid()}"}

    def event(channel=CollaborationChannel.Api):
        return service.list_audit(actor, meta["uri"], channel=channel)["items"][0]

    assert event()["source_link"] == expected
    assert "Private source title" not in json.dumps(event())
    with DbSession.atomic() as db:
        card.visibility = "PRIVATE"
        card.owner_user_id = actor.id
        db.update(card)
    assert "source_link" not in event()
    assert event(CollaborationChannel.HumanUI)["source_link"] == expected
    with DbSession.atomic() as db:
        card.visibility = "SHARED"
        card.owner_user_id = None
        role.actions = []
        db.update(card)
        db.update(role)
    assert "source_link" not in event()
    with DbSession.atomic() as db:
        role.actions = ["read"]
        db.update(role)
    assert event()["source_link"] == expected
    with DbSession.atomic() as db:
        db.delete(member)
    assert "source_link" not in event()
    with DbSession.atomic() as db:
        db.insert(models.ProjectAssignedUser(project_id=project.id, user_id=actor.id))
        card.deleted_at = SafeDateTime.now()
        db.update(card)
    assert "source_link" not in event()
    assert event()["action"] == "created"


def test_wiki_source_links_recheck_native_visibility_and_current_membership(secrets, monkeypatch):
    from langboard_shared.core.db.DbEngine import DbEngine
    from langboard_shared.core.types import SafeDateTime
    from langboard_shared.domain import models
    from langboard_shared.domain.services import DomainService
    from langboard_shared.domain.services.factory.ProjectWikiService import ProjectWikiService
    from langboard_shared.domain.services.factory.SecretReferenceService import SecretAuditSource
    from langboard_shared.domain.services.factory.WorkflowStageService import WorkflowStageService

    service, board, _ = secrets
    actor, project, member, role = board[1:5]
    original_owner_id = project.owner_id
    engine = DbEngine.get_main_engine()
    for model in (models.ProjectWiki, models.ProjectWikiAssignedUser):
        model.__table__.create(engine, checkfirst=True)
    domain = DomainService()
    monkeypatch.setattr(
        service,
        "_get_service",
        lambda cls: domain.project_wiki
        if cls is ProjectWikiService
        else board[0]
        if cls is WorkflowStageService
        else None,
    )
    with DbSession.atomic() as db:
        wiki = models.ProjectWiki(project_id=project.id, title="Sensitive source wiki", is_public=True)
        db.insert(wiki)
    meta = service.create(
        actor,
        "personal",
        "me",
        "history/wiki-source",
        SecretStr("fixture-sensitive"),
        source=SecretAuditSource("wiki", wiki.get_uid()),
    )
    monkeypatch.setattr(KeyVault, "get_key", lambda *_: pytest.fail("Wiki source history read material"))
    expected = {"kind": "wiki", "href": f"/board/{project.get_uid()}/wiki/{wiki.get_uid()}"}

    def event():
        return service.list_audit(actor, meta["uri"])["items"][0]

    assert event()["source_link"] == expected
    assert "Sensitive source wiki" not in json.dumps(event())
    with DbSession.atomic() as db:
        wiki.is_public = False
        db.update(wiki)
    assert "source_link" not in event()
    with DbSession.atomic() as db:
        assignment = models.ProjectWikiAssignedUser(
            project_assigned_id=member.id,
            project_wiki_id=wiki.id,
            user_id=actor.id,
        )
        db.insert(assignment)
    assert event()["source_link"] == expected
    with DbSession.atomic() as db:
        db.delete(assignment)
    assert "source_link" not in event()
    with DbSession.atomic() as db:
        project.owner_id = actor.id
        db.update(project)
    assert event()["source_link"] == expected
    with DbSession.atomic() as db:
        project.owner_id = original_owner_id
        wiki.is_public = True
        role.actions = []
        db.update(project)
        db.update(wiki)
        db.update(role)
    assert "source_link" not in event()
    with DbSession.atomic() as db:
        role.actions = ["read"]
        db.update(role)
    assert event()["source_link"] == expected
    with DbSession.atomic() as db:
        db.delete(member)
    assert "source_link" not in event()
    with DbSession.atomic() as db:
        db.insert(models.ProjectAssignedUser(project_id=project.id, user_id=actor.id))
        wiki.deleted_at = SafeDateTime.now()
        db.update(wiki)
    assert "source_link" not in event()
    assert event()["action"] == "created"
