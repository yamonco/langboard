# ruff: noqa: F811
"""Native card/metadata/lineage writes; current app scope before every replay."""

from concurrent.futures import ThreadPoolExecutor
from json import loads
import pytest
from langboard_shared.core.db import BaseDbModel, DbSession, SqlBuilder
from langboard_shared.core.db.DbEngine import DbEngine
from langboard_shared.domain.models import (
    AppConnection,
    AppDefinition,
    AppResourceBinding,
    BoardAppBinding,
    Card,
    CardMetadata,
    ExternalImportRecord,
    ProjectAssignedUser,
    WorkflowStageDefinition,
)
from langboard_shared.domain.services.AppCardCreation import AppCardCreationConflict, create_app_card
from langboard_shared.domain.services.AppConnectionAuthentication import issue_connection_credential
from langboard_shared.domain.services.AppGovernance import AppGovernanceDenied
from langboard_shared.domain.services.factory.CardService import CardService
from langboard_shared.domain.services.factory.WorkflowStageService_app_test import board  # noqa: F401
from langboard_shared.Env import Env
from langboard_shared.helpers import ensure_models_imported
from sqlalchemy import text


PRESENTATION = {
    "version": 1,
    "key": "app.example-erp.issue",
    "axis": "type",
    "name": "ERP issue",
    "description": "Issue reported by an external ERP application.",
    "icon": "📋",
}


@pytest.fixture
def creation(board, monkeypatch):
    _, actor, project, member, role, columns, stages = board
    engine = DbEngine.get_main_engine()
    if engine.dialect.name != "postgresql":
        pytest.skip("Native card creation requires PostgreSQL sequence/readiness SQL")
    from langboard_shared.domain.models import Organization
    from sqlalchemy.schema import CreateColumn

    # The shared board fixture provides only the organization ID FK stub.
    with engine.begin() as db:
        for column in Organization.__table__.columns:
            if column.name != "id":
                db.execute(
                    text(
                        "ALTER TABLE organization ADD COLUMN "
                        + str(CreateColumn(column).compile(dialect=engine.dialect))
                    )
                )
    ensure_models_imported()
    BaseDbModel.metadata.create_all(engine)
    if engine.dialect.name == "postgresql":
        with engine.begin() as db:
            db.execute(text("CREATE SEQUENCE content_change_seq"))
    monkeypatch.setattr(DbEngine, "get_readonly_engine", DbEngine.get_main_engine)
    monkeypatch.setattr(type(Env), "CARD_INTERNAL_ACCESS_MODE", property(lambda _: "project_members"))
    events = []
    monkeypatch.setattr(CardService, "dispatch_created", lambda self, *args: events.append(args[3].get_uid()))
    with DbSession.atomic() as db:
        project.owner_id = actor.id
        db.update(project)
        columns[0].workflow_stage = "backlog"
        db.update(columns[0])
        db.insert(WorkflowStageDefinition(key="backlog", name="Backlog", is_builtin=True))
        definition = AppDefinition(
            key="example-erp",
            approved_by=actor.id,
            declaration={
                "schema_version": 1,
                "key": "example-erp",
                "name": "Example ERP",
                "description": "External issues",
                "version": "1.0.0",
                "capabilities": ["resources.read", "cards.create", "cards.presentation"],
                "resource_types": ["project"],
                "workflow_requirements": {"required": ["backlog"], "optional": []},
            },
        )
        db.insert(definition)
        connection = AppConnection(app_key="example-erp", owner_id=actor.id, state="connected")
        db.insert(connection)
        binding = BoardAppBinding(
            project_id=project.id,
            app_key="example-erp",
            state="enabled",
            granted_capabilities=["resources.read", "cards.create", "cards.presentation"],
            workflow_mapping={"backlog": columns[0].get_uid()},
        )
        db.insert(binding)
        resource = AppResourceBinding(
            board_binding_id=binding.id,
            connection_id=connection.id,
            resource_type="project",
            external_resource_id="erp-project",
            access_state="granted",
        )
        db.insert(resource)
    token = issue_connection_credential(actor, connection.id)["token"]
    return board, token, connection, binding, resource, definition, events


def call(creation, **kwargs):
    board, token, _, _, resource, *_ = creation
    return create_app_card(
        token,
        board[2].id,
        resource.id,
        "issue-1",
        kwargs.pop("title", "ERP issue"),
        description="External issue body",
        presentation=kwargs.pop("presentation", PRESENTATION),
        **kwargs,
    )


def test_inbound_connection_and_resource_onboarding(creation):
    from langboard_shared.core.types import SnowflakeID
    from langboard_shared.domain.services import DomainService
    from langboard_shared.domain.services.AppConnectionManagement import (
        create_inbound_connection,
        disconnect_inbound_connection,
        select_inbound_resource,
    )
    from langboard_shared.domain.services.AppRegistry import AppRegistryConflict

    actor, project = creation[0][1:3]
    binding, definition = creation[3], creation[5]
    result = create_inbound_connection(actor, "example-erp", definition.edit_revision())
    connection_id = SnowflakeID.from_short_code(result["connection_uid"])
    service = DomainService().workflow_stage
    args = (service, actor, project.get_uid(), "example-erp", definition.edit_revision(),
            binding.get_uid(), binding.edit_revision(), connection_id, "project", "new-project")
    first = select_inbound_resource(*args)
    again = select_inbound_resource(*args, expected_access_revision=first["access_revision"])
    assert first == again and first["access_revision"] == 1
    with pytest.raises(AppRegistryConflict):
        select_inbound_resource(*args)
    removed = select_inbound_resource(*args, selected=False, expected_access_revision=1)
    assert removed["access_state"] == "revoked" and removed["access_revision"] == 2
    with pytest.raises(AppRegistryConflict):
        select_inbound_resource(*args, expected_access_revision=1)
    restored = select_inbound_resource(*args, expected_access_revision=2)
    assert restored["resource_uid"] == first["resource_uid"] and restored["access_revision"] == 3
    with DbSession.use(readonly=False) as db:
        connection = db.exec(SqlBuilder.select.table(AppConnection).where(AppConnection.id == connection_id)).first()
        assert connection.owner_id == actor.id and connection.credential_reference is None and connection.instance_url == ""
        assert len(db.exec(SqlBuilder.select.table(AppResourceBinding).where(AppResourceBinding.connection_id == connection_id)).all()) == 1
    with pytest.raises(AppRegistryConflict):
        disconnect_inbound_connection(actor, connection_id, "0" * 64)
    disconnected = disconnect_inbound_connection(actor, connection_id, result["revision"])
    assert disconnected["state"] == "disconnected"
    with pytest.raises(AppGovernanceDenied):
        issue_connection_credential(actor, connection_id)


def test_inbound_onboarding_current_authority(creation):
    from langboard_shared.core.types import SnowflakeID
    from langboard_shared.domain.services import DomainService
    from langboard_shared.domain.services.AppConnectionManagement import (
        create_inbound_connection,
        select_inbound_resource,
    )
    from langboard_shared.domain.services.AppRegistry import AppRegistryConflict

    actor, project = creation[0][1:3]
    binding, definition = creation[3], creation[5]
    with pytest.raises(AppRegistryConflict):
        create_inbound_connection(actor, "example-erp", "0" * 64)
    with pytest.raises(AppGovernanceDenied):
        create_inbound_connection(actor, "github", definition.edit_revision())
    result = create_inbound_connection(actor, "example-erp", definition.edit_revision())
    connection_id = SnowflakeID.from_short_code(result["connection_uid"])
    service = DomainService().workflow_stage
    args = (service, actor, project.get_uid(), "example-erp", definition.edit_revision(),
            binding.get_uid(), binding.edit_revision(), connection_id)
    with pytest.raises(ValueError):
        select_inbound_resource(*args, "undeclared", "new-project")
    with DbSession.atomic() as db:
        connection = db.exec(SqlBuilder.select.table(AppConnection).where(AppConnection.id == connection_id)).first()
        connection.owner_id = 2  # Another native user owns this personal connection.
        db.update(connection)
    with pytest.raises(AppGovernanceDenied):
        select_inbound_resource(*args, "project", "new-project")


def test_inbound_organization_authority_and_revocation_cleanup(creation):
    from langboard_shared.core.types import SnowflakeID
    from langboard_shared.domain.models import AppGovernancePolicy, Organization
    from langboard_shared.domain.services import DomainService
    from langboard_shared.domain.services.AppConnectionManagement import (
        create_inbound_connection,
        select_inbound_resource,
    )

    actor, project = creation[0][1:3]
    binding, definition = creation[3], creation[5]
    with DbSession.atomic() as db:
        organization = Organization(name="External organization", slug="external", owner_user_id=2)
        db.insert(organization)
    with pytest.raises(AppGovernanceDenied):
        create_inbound_connection(actor, "example-erp", definition.edit_revision(), organization.id)
    result = create_inbound_connection(actor, "example-erp", definition.edit_revision())
    service = DomainService().workflow_stage
    args = (service, actor, project.get_uid(), "example-erp", definition.edit_revision(),
            binding.get_uid(), binding.edit_revision(), SnowflakeID.from_short_code(result["connection_uid"]), "project", "cleanup")
    selected = select_inbound_resource(*args)
    with DbSession.atomic() as db:
        db.insert(AppGovernancePolicy(scope_key="global", mode="disabled"))
        definition.is_enabled = False
        db.update(definition)
    with pytest.raises(AppGovernanceDenied):
        create_inbound_connection(actor, "example-erp", definition.edit_revision())
    revoked_args = (*args[:4], definition.edit_revision(), *args[5:])
    removed = select_inbound_resource(*revoked_args, selected=False, expected_access_revision=selected["access_revision"])
    assert not removed["selected"] and removed["access_state"] == "revoked"


def test_inbound_receipt_listing_scope_pagination_and_disabled_cleanup(creation):
    from langboard_shared.core.types import SnowflakeID
    from langboard_shared.domain.models import AppGovernancePolicy, Organization
    from langboard_shared.domain.services.AppConnectionManagement import (
        create_inbound_connection,
        disconnect_inbound_connection,
        list_inbound_connections,
    )

    actor, definition = creation[0][1], creation[5]
    created = create_inbound_connection(actor, "example-erp", definition.edit_revision())
    with DbSession.atomic() as db:
        organization = Organization(name="Managed organization", slug="managed", owner_user_id=actor.id)
        db.insert(organization)
        db.insert(AppConnection(app_key="example-erp", owner_id=2, state="connected"))
    org_receipt = create_inbound_connection(actor, "example-erp", definition.edit_revision(), organization.id)
    first = list_inbound_connections(actor, "example-erp", limit=1)
    assert first["items"][0]["connection_uid"] == creation[2].get_uid()
    assert first["next_cursor"] == creation[2].get_uid()
    second = list_inbound_connections(actor, "example-erp", after_id=creation[2].id, limit=1)
    assert second["items"] == [created] and second["next_cursor"] is None
    assert list_inbound_connections(actor, "example-erp", organization_id=organization.id)["items"] == [org_receipt]
    with DbSession.atomic() as db:
        organization.owner_user_id = 2
        db.update(organization)
        db.insert(AppGovernancePolicy(scope_key="global", mode="disabled"))
        definition.is_enabled = False
        db.update(definition)
    with pytest.raises(AppGovernanceDenied):
        list_inbound_connections(actor, "example-erp", organization_id=organization.id)
    receipt = list_inbound_connections(actor, "example-erp", after_id=creation[2].id)["items"][0]
    disconnected = disconnect_inbound_connection(
        actor, SnowflakeID.from_short_code(receipt["connection_uid"]), receipt["revision"]
    )
    assert list_inbound_connections(actor, "example-erp", after_id=creation[2].id)["items"][0] == {
        **created,
        **disconnected,
    }
    with pytest.raises(ValueError):
        list_inbound_connections(actor, "example-erp", limit=51)


def test_native_backlog_presentation_and_replay(creation):
    first = call(creation)
    again = call(creation)
    assert first["created"] and not again["created"]
    assert first["card_uid"] == again["card_uid"] and again["effects_state"] == "dispatched"
    assert creation[-1] == [first["card_uid"]]
    with DbSession.use(readonly=False) as db:
        cards = db.exec(SqlBuilder.select.table(Card)).all()
        assert len(cards) == 1 and cards[0].project_column_id == creation[0][5][0].id
        metadata = db.exec(SqlBuilder.select.table(CardMetadata)).first()
        assert loads(metadata.value) == PRESENTATION
        assert len(db.exec(SqlBuilder.select.table(ExternalImportRecord)).all()) == 1
    with pytest.raises(AppCardCreationConflict):
        call(creation, title="Changed payload")


@pytest.mark.parametrize("revoke", ["resource", "grant", "definition", "column", "shared_personal"])
def test_current_scope_rechecked_before_replay(creation, revoke):
    call(creation)
    board, _, _, binding, resource, definition, _ = creation
    with DbSession.atomic() as db:
        if revoke == "resource":
            resource.is_selected = False
            db.update(resource)
        elif revoke == "grant":
            binding.granted_capabilities = []
            db.update(binding)
        elif revoke == "definition":
            definition.is_enabled = False
            db.update(definition)
        elif revoke == "column":
            board[5][0].workflow_stage = "active"
            db.update(board[5][0])
        else:
            db.insert(ProjectAssignedUser(project_id=board[2].id, user_id=2))
    with pytest.raises(AppGovernanceDenied):
        call(creation)
    assert len(creation[-1]) == 1


def test_foreign_presentation_namespace_cannot_claim_identity(creation):
    with pytest.raises(AppGovernanceDenied):
        call(creation, presentation={**PRESENTATION, "key": "app.other.issue"})
    assert creation[-1] == []


def test_concurrent_postgres_replays_create_one_card(creation):
    if DbEngine.get_main_engine().dialect.name != "postgresql":
        pytest.skip("PostgreSQL row-lock proof")
    with ThreadPoolExecutor(max_workers=4) as pool:
        receipts = list(pool.map(lambda _: call(creation), range(4)))
    assert len({r["card_uid"] for r in receipts}) == 1
    assert sum(r["created"] for r in receipts) == 1
    assert len(creation[-1]) == 1


def test_http_create_replay_conflict_and_authentication(creation):
    import langboard.routes.settings.AppCardCreationApi  # noqa: F401
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from langboard_shared.core.routing import AppRouter

    app = FastAPI()
    app.include_router(AppRouter.api)
    board, token, _, _, resource, *_ = creation
    url = f"/apps/v1/boards/{board[2].get_uid()}/cards"
    body = {
        "resource_uid": resource.get_uid(),
        "external_id": "http-issue",
        "title": "ERP HTTP issue",
        "description": "Issue body",
        "presentation": PRESENTATION,
    }
    with TestClient(app) as client:
        assert client.post(url, json=body).status_code == 401
        headers = {"Authorization": "Bearer " + token}
        first = client.post(url, json=body, headers=headers)
        assert first.status_code == 201, first.text
        again = client.post(url, json=body, headers=headers)
        assert again.status_code == 200 and again.json()["card_uid"] == first.json()["card_uid"]
        assert client.post(url, json={**body, "title": "changed"}, headers=headers).status_code == 409
        assert client.post(url, json={**body, "visibility": "SHARED"}, headers=headers).status_code == 400


def test_effect_failure_retains_one_committed_card_and_no_implicit_retry(creation, monkeypatch):
    def fail(*_):
        raise RuntimeError("private broker credentials must never enter receipts")

    monkeypatch.setattr(CardService, "dispatch_created", fail)
    first = call(creation)
    again = call(creation)
    assert again["card_uid"] == first["card_uid"] and again["effects_state"] == "failed"
    with DbSession.use(readonly=False) as db:
        receipt = db.exec(SqlBuilder.select.table(ExternalImportRecord)).first()
        assert receipt.effects_attempts == 1
        assert "private broker" not in receipt.effects_error
        card = db.exec(SqlBuilder.select.table(Card)).first()
        assert card.visibility == "INTERNAL" and card.owner_user_id is None


def test_presentation_failure_rolls_back_card_and_source_receipt(creation, monkeypatch):
    from langboard_shared.domain.services.factory.MetadataService import MetadataService

    def fail(*_):
        raise ValueError("Rejected presentation persistence")

    monkeypatch.setattr(MetadataService, "save_card", fail)
    with pytest.raises(ValueError, match="Rejected presentation"):
        call(creation)
    with DbSession.use(readonly=False) as db:
        assert db.exec(SqlBuilder.select.table(Card)).all() == []
        assert db.exec(SqlBuilder.select.table(ExternalImportRecord)).all() == []
    assert creation[-1] == []


def test_organization_connection_can_create_in_shared_organization_board(creation):
    from langboard_shared.domain.models import Organization

    board, _, connection, _, _, _, _ = creation
    with DbSession.atomic() as db:
        organization = Organization(name="Example organization", slug="example", owner_user_id=board[1].id)
        db.insert(organization)
        board[2].organization_id = organization.id
        db.update(board[2])
        db.insert(ProjectAssignedUser(project_id=board[2].id, user_id=2))
        connection.ownership = "organization"
        connection.organization_id = organization.id
        db.update(connection)
    token = issue_connection_credential(board[1], connection.id)["token"]
    updated = (board, token, *creation[2:])
    assert call(updated)["created"]
    assert not call(updated)["created"]


def test_explicit_board_consent_enables_then_revokes_creation(creation, monkeypatch):
    from langboard_shared.domain.services.AppRegistry import AppRegistryConflict, set_board_consent
    from langboard_shared.publishers import AppSettingPublisher

    monkeypatch.setattr(AppSettingPublisher, "apps_changed", lambda: None)
    board, _, _, binding, _, definition, _ = creation
    with DbSession.atomic() as db:
        binding.granted_capabilities = []
        binding.state = "disabled"
        db.update(binding)
    with pytest.raises(AppGovernanceDenied):
        call(creation)
    result = set_board_consent(
        board[0],
        board[1],
        board[2].get_uid(),
        "example-erp",
        definition.edit_revision(),
        binding.get_uid(),
        binding.edit_revision(),
        ["resources.read", "cards.create", "cards.presentation"],
    )
    assert result["state"] == "enabled" and not result["stage_transitions_enabled"]
    assert call(creation)["created"]
    with pytest.raises(AppRegistryConflict):
        set_board_consent(
            board[0],
            board[1],
            board[2].get_uid(),
            "example-erp",
            definition.edit_revision(),
            binding.get_uid(),
            binding.edit_revision(),
            [],
        )
    result = set_board_consent(
        board[0],
        board[1],
        board[2].get_uid(),
        "example-erp",
        definition.edit_revision(),
        binding.get_uid(),
        result["revision"],
        [],
    )
    assert result["state"] == "disabled"
    with pytest.raises(AppGovernanceDenied):
        call(creation)


def test_board_consent_cannot_exceed_declaration_or_stale_app_review(creation):
    from langboard_shared.domain.services.AppRegistry import AppRegistryConflict, set_board_consent

    board, _, _, binding, _, definition, _ = creation
    args = (
        board[0],
        board[1],
        board[2].get_uid(),
        "example-erp",
        definition.edit_revision(),
        binding.get_uid(),
        binding.edit_revision(),
    )
    with pytest.raises(ValueError):
        set_board_consent(*args, ["execution.run"])
    with pytest.raises(ValueError):
        set_board_consent(*args, ["cards.create", "cards.create"])
    args = (*args[:4], "0" * 64, *args[5:])
    with pytest.raises(AppRegistryConflict):
        set_board_consent(*args, ["cards.create"])


def test_board_consent_requires_current_management_role(creation):
    from langboard_shared.domain.services.AppRegistry import AppRegistryDenied, set_board_consent

    board, _, _, binding, _, definition, _ = creation
    with DbSession.atomic() as db:
        board[2].owner_id = 2
        db.update(board[2])
        board[4].actions = ["read"]
        db.update(board[4])
    with pytest.raises(AppRegistryDenied):
        set_board_consent(
            board[0],
            board[1],
            board[2].get_uid(),
            "example-erp",
            definition.edit_revision(),
            binding.get_uid(),
            binding.edit_revision(),
            ["cards.create"],
        )


def test_policy_disable_blocks_new_consent_but_allows_explicit_removal(creation, monkeypatch):
    from langboard_shared.domain.models import AppGovernancePolicy
    from langboard_shared.domain.services.AppRegistry import AppRegistryDenied, set_board_consent
    from langboard_shared.publishers import AppSettingPublisher

    monkeypatch.setattr(AppSettingPublisher, "apps_changed", lambda: None)
    board, _, _, binding, _, definition, _ = creation
    with DbSession.atomic() as db:
        db.insert(AppGovernancePolicy(scope_key="global", mode="disabled"))
    args = (
        board[0],
        board[1],
        board[2].get_uid(),
        "example-erp",
        definition.edit_revision(),
        binding.get_uid(),
        binding.edit_revision(),
    )
    with pytest.raises(AppRegistryDenied):
        set_board_consent(*args, ["cards.create"])
    assert set_board_consent(*args, [])["state"] == "disabled"
