# ruff: noqa: F811
"""Generic App context reuses current host authority without provider calls."""

import pytest
from langboard_shared.core.db import DbSession
from langboard_shared.domain.models import AppResourceBinding
from langboard_shared.helpers import InfraHelper
from test_github_installation import board, installation, secrets  # noqa: F401
from test_github_lifecycle import lifecycle  # noqa: F401
from test_github_signal import signal_storage  # noqa: F401


def prepare(state, provider):
    with DbSession.use(readonly=False) as db:
        connection, binding, resource = state[2:5]
        connection.app_key = binding.app_key = provider
        binding.granted_capabilities = ["resources.read"]
        resource.resource_type = "repository" if provider == "github" else "project"
        for row in (connection, binding, resource):
            db.update(row)
    return state[0].workflow_stage, state[1][1], state[1][2].get_uid()


@pytest.mark.parametrize("provider", ["github", "glitchtip", "dokploy"])
def test_generic_provider_context_has_no_secret_material(signal_storage, provider):
    service, user, project = prepare(signal_storage, provider)
    result = service.get_connection_context(user, project)
    assert len(result["items"]) == 1
    assert result["items"][0]["app_key"] == provider
    assert set(result["items"][0]) == {
        "resource_uid",
        "connection_uid",
        "binding_uid",
        "app_key",
        "resource_type",
        "external_resource_id",
        "external_resource_id_truncated",
        "name",
        "access_revision",
        "binding_revision",
        "health",
    }
    assert "secret://" not in str(result) and "credential" not in str(result)


@pytest.mark.parametrize("failure", ["resource", "connection", "binding", "capability", "member", "user", "secret"])
def test_revocation_is_rechecked_without_context_cache(signal_storage, failure):
    service, user, project = prepare(signal_storage, "dokploy")
    assert len(service.get_connection_context(user, project)["items"]) == 1
    with DbSession.use(readonly=False) as db:
        row = signal_storage[4]
        if failure == "resource":
            row.access_state = "revoked"
        elif failure == "connection":
            row = signal_storage[2]
            row.state = "revoked"
        elif failure == "binding":
            row = signal_storage[3]
            row.state = "disabled"
        elif failure == "capability":
            row = signal_storage[3]
            row.granted_capabilities = ["resources.read.extra"]
        elif failure == "member":
            db.delete(signal_storage[1][3])
            row = None
        elif failure == "user":
            row = user
            row.activated_at = None
        elif failure == "secret":
            from langboard_shared.core.db import SqlBuilder
            from langboard_shared.domain.models import SecretReference

            row = db.exec(
                SqlBuilder.select.table(SecretReference).where(
                    SecretReference.id
                    == InfraHelper.convert_id(signal_storage[2].credential_reference.removeprefix("secret://ref/"))
                )
            ).first()
            row.state = "revoked"
        if row is not None:
            db.update(row)
    result = service.get_connection_context(user, project)
    assert result is None or result["items"] == []


def test_resource_cursor_foreign_board_and_bounded_projection(signal_storage):
    service, user, project = prepare(signal_storage, "dokploy")
    with DbSession.use(readonly=False) as db:
        resource = signal_storage[4]
        resource.external_resource_id = "x" * 1000
        resource.resource_path = [{"name": "y" * 1000}]
        db.update(resource)
        for index in range(26):
            db.insert(
                AppResourceBinding(
                    board_binding_id=resource.board_binding_id,
                    connection_id=resource.connection_id,
                    resource_type="project",
                    external_resource_id=str(index),
                    access_state="granted",
                )
            )
    result = service.get_connection_context(user, project)
    assert len(result["items"]) == 25 and result["next_cursor"]
    assert all(len(item["name"]) <= 200 for item in result["items"])
    assert len(service.get_connection_context(user, project, result["next_cursor"])["items"]) == 2
    assert service.get_connection_context(user, "00000000001") is None
    with pytest.raises(ValueError):
        service.get_connection_context(user, project, "bad/cursor")


def test_card_context_uses_native_visibility_before_resource_discovery(monkeypatch):
    from types import SimpleNamespace
    from unittest.mock import Mock
    from langboard.card_workspace.domain.value_objects import CardUnavailableError
    from langboard.mcp_tools import CardMcp

    native = SimpleNamespace(
        core={"uid": "card"},
        workflow={"workflow_guidance": "Current guidance"},
        work_state={"verification_state": "unverified"},
    )
    query = Mock(return_value=SimpleNamespace(card=native))
    monkeypatch.setattr(CardMcp, "query_card_bundle", query)
    monkeypatch.setattr(CardMcp, "_adapter", lambda *args: object())
    resources = Mock(return_value={"items": [], "next_cursor": None, "limit": 25})
    service = SimpleNamespace(workflow_stage=SimpleNamespace(get_connection_context=resources))
    result = CardMcp.get_connection_context("board", object(), service, "card")
    assert result["card"] == {"uid": "card", "workflow": native.workflow, "work_state": native.work_state}
    query.side_effect = CardUnavailableError("Unavailable")
    resources.reset_mock()
    with pytest.raises(CardUnavailableError):
        CardMcp.get_connection_context("board", object(), service, "hidden")
    resources.assert_not_called()


def test_revoked_secret_page_can_continue_without_exposing_resource_uid(signal_storage):
    from langboard_shared.core.db import SqlBuilder
    from langboard_shared.domain.models import AppConnection, SecretReference

    service, user, project = prepare(signal_storage, "dokploy")
    with DbSession.use(readonly=False) as db:
        initial = signal_storage[4]
        reference = db.exec(
            SqlBuilder.select.table(SecretReference).where(
                SecretReference.id
                == InfraHelper.convert_id(signal_storage[2].credential_reference.removeprefix("secret://ref/"))
            )
        ).first()
        reference.state = "revoked"
        db.update(reference)
        hidden = [initial.get_uid()]
        for index in range(24):
            row = AppResourceBinding(
                board_binding_id=initial.board_binding_id,
                connection_id=initial.connection_id,
                resource_type="project",
                external_resource_id=f"revoked-{index}",
                access_state="granted",
            )
            db.insert(row)
            hidden.append(row.get_uid())
        valid_reference = SecretReference(
            scope="personal",
            scope_id=user.id,
            creator_id=user.id,
            name="context-valid",
            provider=reference.provider,
            locator="unused-host-locator",
        )
        db.insert(valid_reference)
        connection = AppConnection(
            app_key="dokploy",
            owner_id=user.id,
            state="connected",
            credential_reference=f"secret://ref/{valid_reference.get_uid()}",
        )
        db.insert(connection)
        valid = AppResourceBinding(
            board_binding_id=initial.board_binding_id,
            connection_id=connection.id,
            resource_type="project",
            external_resource_id="valid",
            access_state="granted",
        )
        db.insert(valid)
    result = service.get_connection_context(user, project)
    assert result["items"] == [] and result["next_cursor"]
    assert not any(uid in str(result) for uid in hidden)
    assert (
        service.get_connection_context(user, project, result["next_cursor"])["items"][0]["resource_uid"]
        == valid.get_uid()
    )


def test_native_card_context_reads_database_visibility_and_workflow(signal_storage, monkeypatch):
    from langboard.card_workspace.domain.value_objects import CardUnavailableError
    from langboard.mcp_tools import CardMcp
    from langboard_shared.core.db.DbEngine import DbEngine
    from langboard_shared.domain.models import Card
    from langboard_shared.domain.services.DomainService import DomainService

    _, actor, project_uid = prepare(signal_storage, "dokploy")
    engine = signal_storage[7]
    # Full native card projections use tables beyond the provider-only fixture.
    Card.__table__.metadata.create_all(engine)
    from sqlalchemy import text

    with engine.begin() as db:
        db.execute(
            text(
                "CREATE TABLE card_execution_generation (card_id BIGINT PRIMARY KEY, execution_generation INTEGER NOT NULL)"
            )
        )
    monkeypatch.setattr(DbEngine, "get_readonly_engine", lambda: engine)
    with DbSession.use(readonly=False) as db:
        column = signal_storage[1][5][0]
        column.description = "Current column guidance"
        db.update(column)
        readable = Card(
            project_id=signal_storage[1][2].id, project_column_id=column.id, title="Current task", visibility="SHARED"
        )
        hidden = Card(
            project_id=readable.project_id,
            project_column_id=column.id,
            title="Do not reveal",
            visibility="PRIVATE",
            owner_user_id=2,
            created_by_user_id=2,
        )
        db.insert(readable)
        db.insert(hidden)
    service = DomainService()
    try:
        result = CardMcp.get_connection_context(project_uid, actor, service, readable.get_uid())
        assert result["card"]["uid"] == readable.get_uid()
        assert "Current column guidance" in result["card"]["workflow"]["workflow_guidance"]
        assert result["card"]["work_state"]["verification_state"] == "unverified"
        assert len(result["resources"]["items"]) == 1
        with DbSession.use(readonly=False) as db:
            signal_storage[4].access_state = "revoked"
            db.update(signal_storage[4])
        revoked = CardMcp.get_connection_context(project_uid, actor, service, readable.get_uid())
        assert revoked["resources"]["items"] == []
        assert revoked["card"]["uid"] == readable.get_uid()
        with pytest.raises(CardUnavailableError):
            CardMcp.get_connection_context(project_uid, actor, service, hidden.get_uid())
        with DbSession.use(readonly=False) as db:
            readable.visibility, readable.owner_user_id, readable.created_by_user_id = "PRIVATE", 2, 2
            db.update(readable)
        with pytest.raises(CardUnavailableError):
            CardMcp.get_connection_context(project_uid, actor, service, readable.get_uid())
    finally:
        service.close()
