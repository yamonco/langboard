# ruff: noqa: F811
"""Actual Inbox receipt, native card creation/readiness and transaction proofs."""

import importlib.util
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from langboard.apps.CardSignal import unlink_check
from langboard.apps.GitHubManifest import GitHubManifestUnavailable
from langboard.apps.SignalInbox import create_signal_card
from langboard_shared.core.db import BaseDbModel, DbSession, SqlBuilder
from langboard_shared.core.db.DbEngine import DbEngine
from langboard_shared.core.security.CollaborationChannel import CollaborationChannel
from langboard_shared.core.types import SafeDateTime
from langboard_shared.domain.models import (
    Card,
    CardAppSignalBinding,
    CardSignalCreation,
    Checkitem,
    Checklist,
)
from langboard_shared.Env import Env
from langboard_shared.helpers import InfraHelper, ensure_models_imported
from sqlalchemy import text
from test_card_signal_projection import scoped  # noqa: F401
from test_dokploy_connection import setup  # noqa: F401
from test_dokploy_signal import refresh, selected  # noqa: F401
from test_github_signal import board, installation, lifecycle, secrets, send, signal_storage  # noqa: F401
from test_signal_inbox import dokploy_inbox  # noqa: F401


@pytest.fixture(params=["github", "application", "compose", "glitchtip"])
def creation_scope(request, monkeypatch, scoped):
    state, card, binding, _ = scoped
    from langboard_shared.domain.models import AppSignal
    from langboard_shared.domain.services import DomainService

    service, board, connection, app_binding, resource, *_ = state
    service.card = DomainService().card
    with DbSession.use(readonly=False) as db:
        binding.is_enabled = False
        db.update(binding)
    if request.param == "github":
        signal_uid = send(state)["signal_uid"]
    elif request.param == "glitchtip":
        from datetime import datetime, timezone
        from langboard.apps.GlitchTipSignal import normalize_issue

        with DbSession.use(readonly=False) as db:
            connection.app_key = app_binding.app_key = "glitchtip"
            app_binding.granted_capabilities = ["resources.read", "signals.read"]
            resource.resource_type = "project"
            resource.external_resource_id = "2"
            resource.resource_path = [
                {"type": "organization", "id": "1", "slug": "test-org"},
                {"type": "project", "id": resource.external_resource_id, "slug": "test-project"},
            ]
            db.update(connection)
            db.update(app_binding)
            db.update(resource)
            normalized = normalize_issue(
                {
                    "id": "101",
                    "project": {"id": "2", "slug": "test-project"},
                    "status": "unresolved",
                    "firstSeen": "2026-10-08T00:00:00Z",
                    "lastSeen": "2026-10-08T00:01:00Z",
                },
                "2",
                "test-project",
                datetime.now(timezone.utc),
            )
            signal = AppSignal(resource_id=resource.id, event_id=normalized["payload_digest"], **normalized)
            db.insert(signal)
            signal_uid = signal.get_uid()
    else:
        from langboard.apps.DokploySignal import normalize_deployment

        kind = request.param
        with DbSession.use(readonly=False) as db:
            connection.app_key = app_binding.app_key = "dokploy"
            app_binding.granted_capabilities = ["signals.read", "deployments.read"]
            resource.resource_type = kind
            resource.resource_path = [
                {"type": "project", "id": "project"},
                {"type": "environment", "id": "env"},
                {"type": kind, "id": resource.external_resource_id, "name": "Native resource"},
            ]
            db.update(connection)
            db.update(app_binding)
            db.update(resource)
            signal = AppSignal(
                resource_id=resource.id,
                **normalize_deployment(
                    {
                        "deploymentId": "dep-1",
                        kind + "Id": resource.external_resource_id,
                        "status": "done",
                        "finishedAt": "2026-10-08T10:01:00Z",
                    },
                    kind,
                    resource.external_resource_id,
                ),
            )
            db.insert(signal)
            signal_uid = signal.get_uid()
    engine = DbEngine.get_main_engine()
    ensure_models_imported()
    needed = {
        "checklist",
        "checkitem",
        "project_execution_binding",
        "webhook_setting",
        "global_card_relationship_type",
        "card_relationship",
        "card_assigned_user",
        "card_assigned_project_label",
        "project_label",
        "user_card_read_state",
    }
    while True:
        previous = len(needed)
        for name in list(needed):
            needed.update(fk.column.table.name for fk in BaseDbModel.metadata.tables[name].foreign_keys)
        if len(needed) == previous:
            break
    BaseDbModel.metadata.create_all(engine, tables=[BaseDbModel.metadata.tables[name] for name in needed])
    path = Path(__file__).resolve().parents[2] / "langboard/migrations/versions/20261008234000-5a76439c86b1.py"
    spec = importlib.util.spec_from_file_location("creation_migration", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    with engine.begin() as db:
        migration.op = Operations(MigrationContext.configure(db))
        migration.upgrade()
        if engine.dialect.name == "postgresql":
            db.execute(text("CREATE SEQUENCE content_change_seq"))
    with DbSession.use(readonly=False) as db:
        board[4].actions = ["read", "update", "card_update"]
        db.update(board[4])
    monkeypatch.setattr(type(Env), "CARD_INTERNAL_ACCESS_MODE", property(lambda _: "project_members"))
    original = Env.get_from_env
    monkeypatch.setattr(
        Env,
        "get_from_env",
        lambda key, default=None: "project_members" if key == "CARD_INTERNAL_ACCESS_MODE" else original(key, default),
    )
    # Suppress only external dispatch; CardService creation/readiness remain native.
    events = []
    from langboard_shared.domain.services.factory.CardService import CardService

    monkeypatch.setattr(CardService, "dispatch_created", lambda self, *args, **kwargs: events.append(args[3].get_uid()))
    return (
        service,
        board,
        connection.get_uid(),
        resource,
        signal_uid,
        engine,
        migration,
        events,
    )


def create(state, title="  Explicit native card  ", actor=None, column_uid=None, channel=CollaborationChannel.Api):
    service, board, connection_uid, resource, signal_uid, *_ = state
    return create_signal_card(
        service,
        actor or board[1],
        board[2].get_uid(),
        connection_uid,
        resource.get_uid(),
        signal_uid,
        column_uid or board[5][0].get_uid(),
        title,
        channel=channel,
    )


def native_only(state):
    if state[5].dialect.name != "postgresql":
        pytest.skip("Ordinary CardService readiness uses native PostgreSQL SQL; exercised on actual PostgreSQL")


def active_card(state, visibility="SHARED", owner=None):
    service, board, _, resource, signal_uid, *_ = state
    from langboard_shared.domain.models import AppSignal

    with DbSession.use(readonly=False) as db:
        signal = db.exec(
            SqlBuilder.select.table(AppSignal).where(AppSignal.id == InfraHelper.convert_id(signal_uid))
        ).first()
        card = Card(
            project_id=board[2].id,
            project_column_id=board[5][0].id,
            title="Existing",
            visibility=visibility,
            owner_user_id=owner,
            created_by_user_id=owner,
            last_change_seq=7,
        )
        db.insert(card)
        binding = CardAppSignalBinding(
            card_id=card.id,
            resource_id=resource.id,
            external_id=signal.external_id,
            commit_sha=signal.commit_sha,
            source_change_seq=7,
        )
        db.insert(binding)
    return card, binding


def test_receipt_reuses_visible_binding_and_survives_unlink(creation_scope):
    state = creation_scope
    card, binding = active_card(state)
    result = create(state)
    assert result == {"card_uid": card.get_uid(), "created": False}
    service, board, *_ = state
    unlink_check(service, board[1], board[2].get_uid(), card.get_uid(), binding.get_uid(), 0)
    assert create(state, "Different title") == result
    with DbSession.use(readonly=False) as db:
        assert len(db.exec(SqlBuilder.select.table(CardSignalCreation)).all()) == 1
        assert (
            not db.exec(SqlBuilder.select.table(CardAppSignalBinding).where(CardAppSignalBinding.id == binding.id))
            .first()
            .is_enabled
        )
        card.visibility = "PRIVATE"
        card.owner_user_id = 2
        card.created_by_user_id = 2
        db.update(card)
    with pytest.raises(GitHubManifestUnavailable):
        create(state)


def test_native_create_receipt_checklist_readiness_and_replay(creation_scope):
    native_only(creation_scope)
    state = creation_scope
    result = create(state)
    assert result["created"]
    assert create(state) == {"card_uid": result["card_uid"], "created": False}
    service, board, *_ = state
    from langboard_shared.helpers import InfraHelper

    with DbSession.use(readonly=False) as db:
        card = db.exec(
            SqlBuilder.select.table(Card).where(Card.id == InfraHelper.convert_id(result["card_uid"]))
        ).first()
        assert card.title == "Explicit native card" and card.visibility == "INTERNAL"
        assert card.created_by_user_id == board[1].id and card.last_change_seq > 0
        checklists = db.exec(SqlBuilder.select.table(Checklist).where(Checklist.card_id == card.id)).all()
        assert len(checklists) == 1 and checklists[0].is_system and not checklists[0].is_checked
        assert (
            db.exec(SqlBuilder.select.table(Checkitem).where(Checkitem.checklist_id == checklists[0].id)).first().title
            == card.title
        )
        binding = db.exec(
            SqlBuilder.select.table(CardAppSignalBinding).where(CardAppSignalBinding.card_id == card.id)
        ).first()
        assert binding.source_change_seq == card.last_change_seq
    assert state[7] == [result["card_uid"]]


def test_native_creation_binding_failure_rolls_back_everything(creation_scope, monkeypatch):
    native_only(creation_scope)
    from langboard.apps import CardSignal

    state = creation_scope
    with DbSession.use(readonly=False) as db:
        before = len(db.exec(SqlBuilder.select.table(Card)).all())

    def fail(*args, **kwargs):
        raise RuntimeError("Injected bind failure")

    monkeypatch.setattr(CardSignal, "bind_check", fail)
    with pytest.raises(RuntimeError, match="Injected bind failure"):
        create(state)
    with DbSession.use(readonly=False) as db:
        assert len(db.exec(SqlBuilder.select.table(Card)).all()) == before
        assert db.exec(SqlBuilder.select.table(CardSignalCreation)).all() == []
        assert db.exec(SqlBuilder.select.table(Checklist)).all() == []
    assert state[7] == []


def test_native_concurrent_same_identity_creates_once(creation_scope):
    native_only(creation_scope)
    with ThreadPoolExecutor(max_workers=2) as workers:
        results = list(workers.map(lambda _: create(creation_scope), range(2)))
    assert sum(row["created"] for row in results) == 1
    assert len({row["card_uid"] for row in results}) == 1
    assert len(creation_scope[7]) == 1
    with DbSession.use(readonly=False) as db:
        assert len(db.exec(SqlBuilder.select.table(CardSignalCreation)).all()) == 1


@pytest.mark.parametrize(
    "failure", ["role", "column", "archive", "deleted", "secret", "selection", "resource", "connection"]
)
def test_creation_current_authority_before_any_card_write(creation_scope, failure):
    from langboard_shared.domain.models import AppConnection, SecretReference

    state = creation_scope
    service, board, _, resource, *_ = state
    with DbSession.use(readonly=False) as db:
        before = len(db.exec(SqlBuilder.select.table(Card)).all())
        if failure == "role":
            board[4].actions = ["read", "update"]
            db.update(board[4])
        elif failure in {"column", "archive", "deleted"}:
            column = board[5][0]
            if failure == "column":
                column.project_id = 11
            elif failure == "archive":
                column.is_archive = True
            else:
                column.deleted_at = SafeDateTime.now()
            db.update(column)
        elif failure == "secret":
            connection = db.exec(SqlBuilder.select.table(AppConnection)).first()
            secret = db.exec(
                SqlBuilder.select.table(SecretReference).where(
                    SecretReference.id == InfraHelper.convert_id(connection.credential_reference.split("/")[-1])
                )
            ).first()
            secret.state = "revoked"
            db.update(secret)
        elif failure in {"selection", "resource"}:
            if failure == "selection":
                resource.is_selected = False
            else:
                resource.access_state = "revoked"
            db.update(resource)
        else:
            connection = db.exec(SqlBuilder.select.table(AppConnection)).first()
            connection.state = "disconnected"
            db.update(connection)
    with pytest.raises(GitHubManifestUnavailable):
        create(state)
    with DbSession.use(readonly=False) as db:
        assert len(db.exec(SqlBuilder.select.table(Card)).all()) == before
        assert not db.exec(SqlBuilder.select.table(CardSignalCreation)).all()


def test_creation_migration_rollback_refuses_receipt_loss(creation_scope):
    state = creation_scope
    active_card(state)
    create(state)
    with state[5].begin() as connection:
        state[6].op = Operations(MigrationContext.configure(connection))
        with pytest.raises(RuntimeError, match="Cannot discard"):
            state[6].downgrade()


def test_native_owner_private_default_and_replay(creation_scope):
    native_only(creation_scope)
    _, board, *_ = creation_scope
    with DbSession.use(readonly=False) as db:
        board[2].owner_id = board[1].id
        db.update(board[2])
    result = create(creation_scope, channel=CollaborationChannel.HumanUI)
    with DbSession.use(readonly=False) as db:
        card = db.exec(
            SqlBuilder.select.table(Card).where(Card.id == InfraHelper.convert_id(result["card_uid"]))
        ).first()
        assert card.visibility == "PRIVATE" and card.owner_user_id == board[1].id
    assert create(creation_scope, channel=CollaborationChannel.HumanUI) == {
        "card_uid": result["card_uid"],
        "created": False,
    }
    with pytest.raises(GitHubManifestUnavailable):
        create(creation_scope)


def test_hidden_other_actor_card_does_not_consume_creation(creation_scope):
    native_only(creation_scope)
    hidden, _ = active_card(creation_scope, "PRIVATE", 2)
    result = create(creation_scope)
    assert result["created"] and result["card_uid"] != hidden.get_uid()


def test_deleted_receipt_target_cannot_recreate_or_return_metadata(creation_scope):
    card, _ = active_card(creation_scope)
    create(creation_scope)
    with DbSession.use(readonly=False) as db:
        card.deleted_at = SafeDateTime.now()
        db.update(card)
    with pytest.raises(GitHubManifestUnavailable):
        create(creation_scope)
    with DbSession.use(readonly=False) as db:
        assert len(db.exec(SqlBuilder.select.table(CardSignalCreation)).all()) == 1


@pytest.mark.parametrize("board", ["sqlite-http", "postgresql-test"], indirect=True)
def test_native_http_creation_form_status_replay_and_auth(creation_scope, monkeypatch):
    import importlib
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from langboard.middlewares.ApiAuthMiddleware import ApiAuthMiddleware
    from langboard.routes.board.SignalInboxApi import create_inbox_card
    from langboard_shared.core.routing import AppRouter
    from langboard_shared.core.security import AuthSecurity

    state = creation_scope
    service, board, connection_uid, resource, signal_uid, engine, *_ = state
    service.close = lambda: None
    if engine.dialect.name == "sqlite":
        active_card(state)
    monkeypatch.setattr(DbEngine, "get_readonly_engine", DbEngine.get_main_engine)
    monkeypatch.setattr(
        importlib.import_module("langboard.middlewares.ApiAuthMiddleware"), "DomainService", lambda: service
    )
    app = FastAPI()
    app.include_router(AppRouter.api)
    app.add_middleware(ApiAuthMiddleware, routes=AppRouter.api.routes)
    for route in app.routes:
        if getattr(route, "endpoint", None) == create_inbox_card:
            for dependency in route.dependant.dependencies:
                if dependency.name == "service":
                    app.dependency_overrides[dependency.call] = lambda: service
    form = dict(
        connection_uid=connection_uid,
        resource_uid=resource.get_uid(),
        signal_uid=signal_uid,
        project_column_uid=board[5][0].get_uid(),
        title="  Native HTTP card  ",
    )
    url = f"/board/{board[2].get_uid()}/signals/inbox/card"
    with TestClient(app, base_url="https://testserver") as client:
        assert client.post(url, json=form).status_code == 401
        access, refresh = AuthSecurity.authenticate(board[1].id)
        client.cookies.set(Env.REFRESH_TOKEN_NAME, refresh)
        headers = {"Authorization": f"Bearer {access}"}
        result = client.post(url, json=form, headers=headers)
        assert result.status_code == (201 if engine.dialect.name == "postgresql" else 200), result.text
        replay = client.post(url, json=form, headers=headers)
        assert replay.status_code == 200 and replay.json()["card_uid"] == result.json()["card_uid"]
        for bad in (
            {"title": " "},
            {"title": "x" * 201},
            {"title": True},
            {"extra": "invalid"},
            {"signal_uid": "../invalid"},
        ):
            assert client.post(url, json={**form, **bad}, headers=headers).status_code in {400, 422}
        with DbSession.use(readonly=False) as db:
            board[4].actions = ["read", "update"]
            db.update(board[4])
        assert client.post(url, json=form, headers=headers).status_code == 404
