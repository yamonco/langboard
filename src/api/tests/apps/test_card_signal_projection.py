# ruff: noqa: F811
"""Explicit card evidence, native current authority and occurrence-order regression."""

import importlib.util
from pathlib import Path
import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from langboard_shared.core.db import DbSession
from langboard_shared.domain.models import Card, CardAppSignalBinding, Organization
from langboard_shared.domain.services.AppSignalProjection import card_signal_projections
from sqlalchemy import event
from test_github_signal import board, installation, lifecycle, secrets, send, signal_storage  # noqa: F401


@pytest.fixture
def scoped(signal_storage):
    state = signal_storage
    engine = state[7]
    from langboard_shared.domain.models import EmployeeMembershipPolicy, ScimGroup, ScimGroupMember, UserIdentityLink

    for model in (EmployeeMembershipPolicy, ScimGroup, ScimGroupMember, UserIdentityLink):
        model.__table__.create(engine, checkfirst=True)
    Card.__table__.create(engine)
    path = Path(__file__).resolve().parents[2] / "langboard/migrations/versions/20261008125000-1ba745ac6de6.py"
    spec = importlib.util.spec_from_file_location("card_signal_migration", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    with engine.begin() as db:
        migration.op = Operations(MigrationContext.configure(db))
        migration.upgrade()
    with DbSession.use(readonly=False) as db:
        card = Card(
            project_id=state[1][2].id,
            project_column_id=state[1][5][0].id,
            title="Explicit evidence",
            visibility="SHARED",
            last_change_seq=7,
        )
        db.insert(card)
        binding = CardAppSignalBinding(
            card_id=card.id, resource_id=state[4].id, external_id="55", commit_sha="a" * 40, source_change_seq=7
        )
        db.insert(binding)
    return state, card, binding, migration


def evidence(scoped):
    _, card, _, _ = scoped
    return card_signal_projections([card])[card.id][0]


def test_occurrence_order_exact_scope_conflict_and_staleness(scoped):
    state, card, _, _ = scoped
    assert evidence(scoped)["state"] == "unavailable"
    send(state)
    assert evidence(scoped)["state"] == "passed"
    state[5]["check_run"].update(conclusion="failure", completed_at="2026-10-08T02:00:00Z")
    send(state)
    assert evidence(scoped)["state"] == "failed"
    state[5]["check_run"].update(conclusion="success", completed_at="2026-10-08T01:00:00Z")
    send(state)
    assert evidence(scoped)["state"] == "failed"
    state[5]["check_run"].update(head_sha="b" * 40, completed_at="2026-10-08T03:00:00Z")
    send(state)
    state[5]["check_run"].update(head_sha="a" * 40, id=56)
    send(state)
    assert evidence(scoped)["state"] == "failed"
    state[5]["check_run"].update(id=55, completed_at="2026-10-08T02:00:00Z")
    send(state)
    assert evidence(scoped)["state"] == "conflict" and evidence(scoped)["outcome"] is None
    with DbSession.use(readonly=False) as db:
        card.last_change_seq = 8
        db.update(card)
    assert evidence(scoped)["state"] == "stale"
    with state[7].begin() as db:
        scoped[3].op = Operations(MigrationContext.configure(db))
        with pytest.raises(RuntimeError, match="Cannot discard"):
            scoped[3].downgrade()


@pytest.mark.parametrize(
    "failure",
    [
        "unlink",
        "resource",
        "connection",
        "grant",
        "role",
        "member",
        "inactive",
        "secret",
        "scope",
        "card_binding",
        "card_deleted",
        "board_deleted",
    ],
)
def test_current_revocation_suppresses_evidence(scoped, failure):
    state, card, binding, _ = scoped
    send(state)
    with DbSession.use(readonly=False) as db:
        target = state[4]
        if failure == "unlink":
            target.is_selected = False
        elif failure == "resource":
            target.access_state = "revoked"
        elif failure == "connection":
            target = state[2]
            target.state = "disconnected"
        elif failure == "grant":
            target = state[3]
            target.granted_capabilities = ["signals.read.extra"]
        elif failure == "role":
            target = state[1][4]
            target.actions = ["read"]
        elif failure == "member":
            db.delete(state[1][3])
            target = None
        elif failure == "inactive":
            target = state[1][1]
            target.activated_at = None
        elif failure == "scope":
            target = state[2]
            target.credential_reference = "secret://ref/invalid!"
        elif failure == "card_binding":
            target = binding
            target.is_enabled = False
        elif failure in {"card_deleted", "board_deleted"}:
            from langboard_shared.core.types import SafeDateTime

            target = card if failure == "card_deleted" else state[1][2]
            target.deleted_at = SafeDateTime.now()
        else:
            service = state[0].secret_reference
            service.revoke(
                state[1][1],
                state[2].credential_reference,
                service.get_metadata(state[1][1], state[2].credential_reference)["revision"],
            )
            target = None
        if target is not None:
            db.update(target)
    assert card_signal_projections([card]) == {}


@pytest.mark.parametrize("scope", ["project", "workspace"])
def test_native_nonpersonal_secret_scope_and_revocation(scoped, scope):
    from pydantic import SecretStr

    state, card, _, _ = scoped
    actor = state[1][1]
    owner_scope = state[1][2]
    if scope == "workspace":
        with DbSession.use(readonly=False) as db:
            owner_scope = Organization(name="Fixture", slug="fixture", owner_user_id=actor.id)
            db.insert(owner_scope)
    meta = state[0].secret_reference.create(actor, scope, owner_scope.get_uid(), "github/scoped", SecretStr("fixture"))
    with DbSession.use(readonly=False) as db:
        state[2].credential_reference = meta["uri"]
        db.update(state[2])
    assert evidence(scoped)["state"] == "unavailable"
    with DbSession.use(readonly=False) as db:
        if scope == "workspace":
            owner_scope.is_active = False
        else:
            owner_scope.owner_id = 2
            db.delete(state[1][3])
        db.update(owner_scope)
    assert card_signal_projections([card]) == {}


def test_batch_has_constant_query_count(scoped):
    state, card, _, _ = scoped
    cards = [card]
    with DbSession.use(readonly=False) as db:
        for _ in range(30):
            another = Card(
                project_id=card.project_id,
                project_column_id=card.project_column_id,
                title="Batch",
                visibility="SHARED",
                last_change_seq=7,
            )
            db.insert(another)
            db.insert(
                CardAppSignalBinding(
                    card_id=another.id,
                    resource_id=state[4].id,
                    external_id="55",
                    commit_sha="a" * 40,
                    source_change_seq=7,
                )
            )
            cards.append(another)
    statements = []

    def record(*args):
        statements.append(args[2])

    event.listen(state[7], "before_cursor_execute", record)
    try:
        assert len(card_signal_projections(cards)) == 31
        assert len(statements) == 3
    finally:
        event.remove(state[7], "before_cursor_execute", record)


@pytest.mark.parametrize("board", ["sqlite-http"], indirect=True)
def test_native_authenticated_card_binding_http(scoped, monkeypatch):
    import importlib
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from langboard.middlewares.ApiAuthMiddleware import ApiAuthMiddleware
    from langboard.routes.board.CardSignalApi import (
        attach_card_signal,
        get_card_signal_resources,
        get_card_signals,
        unlink_card_signal,
    )
    from langboard_shared.core.db.DbEngine import DbEngine
    from langboard_shared.core.routing import AppRouter
    from langboard_shared.core.security import AuthSecurity
    from langboard_shared.domain.services import DomainService
    from langboard_shared.Env import Env

    state, card, binding, _ = scoped
    service = state[0]
    domain = DomainService()
    service.card = domain.card
    service.close = lambda: None
    monkeypatch.setattr(DbEngine, "get_readonly_engine", DbEngine.get_main_engine)
    monkeypatch.setattr(
        importlib.import_module("langboard.middlewares.ApiAuthMiddleware"), "DomainService", lambda: service
    )
    with DbSession.use(readonly=False) as db:
        state[1][4].actions = ["read", "update", "card_update"]
        db.update(state[1][4])
        db.delete(binding)
    signal_uid = send(state)["signal_uid"]
    app = FastAPI()
    app.include_router(AppRouter.api)
    app.add_middleware(ApiAuthMiddleware, routes=AppRouter.api.routes)
    for route in app.routes:
        if getattr(route, "endpoint", None) in {
            get_card_signals,
            attach_card_signal,
            unlink_card_signal,
            get_card_signal_resources,
        }:
            for dependency in route.dependant.dependencies:
                if dependency.name == "service":
                    app.dependency_overrides[dependency.call] = lambda: service
    url = f"/board/{state[1][2].get_uid()}/card/{card.get_uid()}/signals"
    form = dict(
        connection_uid=state[2].get_uid(), resource_uid=state[4].get_uid(), signal_uid=signal_uid, source_change_seq=7
    )
    try:
        with TestClient(app, base_url="https://testserver") as client:
            assert client.post(url, json=form).status_code == 401
            access, refresh = AuthSecurity.authenticate(state[1][1].id)
            client.cookies.set(Env.REFRESH_TOKEN_NAME, refresh)
            headers = {"Authorization": f"Bearer {access}"}
            result = client.post(url, json=form, headers=headers)
            assert result.status_code == 200, result.text
            linked = result.json()
            assert client.get(url + "/resources", headers=headers).status_code == 200
            assert client.get(url + "/resources", headers=headers).json()["items"][0]["uid"] == state[4].get_uid()
            assert client.get(url, headers=headers).json()["items"][0]["state"] == "passed"
            assert client.post(url, json=form, headers=headers).status_code == 409
            assert (
                client.post(
                    url, json={**form, "source_change_seq": 6, "expected_revision": 0}, headers=headers
                ).status_code
                == 409
            )
            assert client.post(url, json={**form, "source_change_seq": True}, headers=headers).status_code == 400
            with DbSession.use(readonly=False) as db:
                card.visibility = "INTERNAL"
                db.update(card)
            assert client.get(url, headers=headers).status_code == 404
            assert client.post(url, json={**form, "expected_revision": 0}, headers=headers).status_code == 404
            with DbSession.use(readonly=False) as db:
                card.visibility = "SHARED"
                db.update(card)
                state[4].is_selected = False
                db.update(state[4])
            snapshot = client.get(url, headers=headers).json()
            assert snapshot["items"] == []
            assert snapshot["bindings"] == [{"binding_uid": linked["binding_uid"], "revision": 0}]
            assert snapshot["source_change_seq"] == 7
            assert client.post(url, json={**form, "expected_revision": 0}, headers=headers).status_code == 404
            unlink = url + "/" + linked["binding_uid"] + "/unlink"
            assert client.post(unlink, json={"expected_revision": 1}, headers=headers).status_code == 409
            result = client.post(unlink, json={"expected_revision": 0}, headers=headers)
            assert result.status_code == 200 and result.json()["is_enabled"] is False
            with DbSession.use(readonly=False) as db:
                state[4].is_selected = True
                db.update(state[4])
            result = client.post(url, json={**form, "expected_revision": 1}, headers=headers)
            assert result.status_code == 200 and result.json()["revision"] == 2
            with DbSession.use(readonly=False) as db:
                state[1][4].actions = ["read", "update"]
                db.update(state[1][4])
            assert client.post(unlink, json={"expected_revision": 2}, headers=headers).status_code == 404
    finally:
        domain.close()


def test_native_mutation_authority_scope_limit_and_revision(scoped):
    from langboard.apps.CardSignal import CardSignalConflict, bind_check, unlink_check
    from langboard.apps.GitHubManifest import GitHubManifestUnavailable
    from langboard_shared.core.db import SqlBuilder
    from langboard_shared.domain.models import SecretReference
    from langboard_shared.domain.services import DomainService
    from langboard_shared.helpers import InfraHelper

    state, card, binding, _ = scoped
    domain = DomainService()
    service = state[0]
    service.card = domain.card
    actor = state[1][1]
    with DbSession.use(readonly=False) as db:
        state[1][4].actions = ["read", "update", "card_update"]
        db.update(state[1][4])
    signal_uid = send(state)["signal_uid"]
    args = (
        service,
        actor,
        state[1][2].get_uid(),
        card.get_uid(),
        state[2].get_uid(),
        state[4].get_uid(),
        signal_uid,
        7,
    )
    try:
        assert bind_check(*args, 0)["revision"] == 1
        with pytest.raises(GitHubManifestUnavailable):
            bind_check(
                service,
                actor,
                state[1][2].get_uid(),
                card.get_uid(),
                state[2].get_uid(),
                state[4].get_uid(),
                card.get_uid(),
                7,
                1,
            )
        with DbSession.use(readonly=False) as db:
            reference = db.exec(
                SqlBuilder.select.table(SecretReference).where(
                    SecretReference.id == InfraHelper.convert_id(state[2].credential_reference.split("/")[-1])
                )
            ).first()
            reference.state = "revoked"
            db.update(reference)
        with pytest.raises(GitHubManifestUnavailable):
            bind_check(*args, 1)
        with DbSession.use(readonly=False) as db:
            reference.state = "active"
            db.update(reference)
        unlink_check(service, actor, state[1][2].get_uid(), card.get_uid(), binding.get_uid(), 1)
        with DbSession.use(readonly=False) as db:
            for number in range(25):
                db.insert(
                    CardAppSignalBinding(
                        card_id=card.id,
                        resource_id=state[4].id,
                        external_id=str(1000 + number),
                        commit_sha="a" * 40,
                        source_change_seq=7,
                    )
                )
        with pytest.raises(CardSignalConflict):
            bind_check(*args, 2)
        with DbSession.use(readonly=False) as db:
            card.visibility = "PRIVATE"
            card.owner_user_id = 2
            card.created_by_user_id = 2
            db.update(card)
        with pytest.raises(GitHubManifestUnavailable):
            bind_check(*args, 2)
    finally:
        domain.close()


def test_current_db_card_revision_overrules_old_snapshot(scoped):
    from copy import copy

    state, card, _, _ = scoped
    send(state)
    old = copy(card)
    with DbSession.use(readonly=False) as db:
        card.last_change_seq = 8
        db.update(card)
    assert card_signal_projections([old])[card.id][0]["state"] == "stale"


def test_card_resource_discovery_is_read_scoped_and_batched(scoped):
    from langboard.apps.CardSignal import list_card_resources
    from langboard.apps.GitHubManifest import GitHubManifestUnavailable
    from langboard_shared.domain.models import AppResourceBinding, BoardAppBinding
    from langboard_shared.domain.services import DomainService

    state, card, _, _ = scoped
    domain = DomainService()
    service = state[0]
    service.card = domain.card
    # Read-only caller, different from the connection owner. Owner retains Update consumption authority.
    with DbSession.use(readonly=False) as db:
        from langboard_shared.core.types import SafeDateTime
        from langboard_shared.domain.models import ProjectAssignedUser, ProjectRole, User

        reader = User(
            firstname="Read",
            lastname="Only",
            email="reader2@example.invalid",
            password="fixture",
            activated_at=SafeDateTime.now(),
        )
        db.insert(reader)
        db.insert(ProjectAssignedUser(project_id=card.project_id, user_id=reader.id))
        db.insert(ProjectRole(project_id=card.project_id, user_id=reader.id, actions=["read"]))
        for number in range(30):
            db.insert(
                AppResourceBinding(
                    board_binding_id=state[3].id,
                    connection_id=state[2].id,
                    resource_type="repository",
                    external_resource_id=str(1000 + number),
                    access_state="granted",
                    resource_path=[{"type": "repository", "id": str(1000 + number), "name": f"fixture/{number}"}],
                )
            )
        foreign = BoardAppBinding(
            project_id=11, app_key="github", state="enabled", granted_capabilities=["signals.read"]
        )
        db.insert(foreign)
        db.insert(
            AppResourceBinding(
                board_binding_id=foreign.id,
                connection_id=state[2].id,
                resource_type="repository",
                external_resource_id="foreign",
                access_state="granted",
            )
        )
    statements = []

    def record(*args):
        statements.append(args[2])

    event.listen(state[7], "before_cursor_execute", record)
    try:
        first = list_card_resources(service, reader, state[1][2].get_uid(), card.get_uid())
        assert len(first["items"]) == 25 and first["next_cursor"]
        assert len(statements) <= 12
        second = list_card_resources(service, reader, state[1][2].get_uid(), card.get_uid(), first["next_cursor"])
        assert len(second["items"]) == 6 and second["next_cursor"] is None
        assert "foreign" not in str(first) + str(second)
        with pytest.raises(ValueError):
            list_card_resources(service, reader, state[1][2].get_uid(), card.get_uid(), "!invalid")
        with DbSession.use(readonly=False) as db:
            state[1][4].actions = ["read"]
            db.update(state[1][4])
        assert list_card_resources(service, reader, state[1][2].get_uid(), card.get_uid())["items"] == []
        with DbSession.use(readonly=False) as db:
            card.visibility = "INTERNAL"
            db.update(card)
        with pytest.raises(GitHubManifestUnavailable):
            list_card_resources(service, reader, state[1][2].get_uid(), card.get_uid())
    finally:
        event.remove(state[7], "before_cursor_execute", record)
        domain.close()


def test_binding_notifications_follow_commit_and_conflicts_do_not_publish(scoped, monkeypatch):
    from langboard.apps.CardSignal import CardSignalConflict, bind_check, unlink_check
    from langboard_shared.domain.services import DomainService
    from langboard_shared.publishers import CardPublisher

    state, card, binding, _ = scoped
    domain = DomainService()
    state[0].card = domain.card
    with DbSession.use(readonly=False) as db:
        state[1][4].actions = ["read", "update", "card_update"]
        db.update(state[1][4])
    signal_uid = send(state)["signal_uid"]
    notifications = []
    monkeypatch.setattr(CardPublisher, "app_signal_changed", notifications.append)
    args = (
        state[0],
        state[1][1],
        state[1][2].get_uid(),
        card.get_uid(),
        state[2].get_uid(),
        state[4].get_uid(),
        signal_uid,
    )
    try:
        with pytest.raises(RuntimeError, match="rollback fixture"):
            with DbSession.atomic():
                bind_check(*args, 7, 0)
                assert notifications == []
                raise RuntimeError("rollback fixture")
        assert notifications == []
        assert bind_check(*args, 7, 0)["revision"] == 1
        assert notifications == [state[1][2].get_uid()]
        with pytest.raises(CardSignalConflict):
            bind_check(*args, 6, 1)
        assert len(notifications) == 1
        unlink_check(state[0], state[1][1], state[1][2].get_uid(), card.get_uid(), binding.get_uid(), 1)
        assert len(notifications) == 2
        assert card.last_change_seq == 7
    finally:
        domain.close()


def test_global_app_policy_hides_existing_evidence_without_deleting_it(scoped):
    from langboard_shared.domain.models import AppGovernancePolicy

    state, card, _, _ = scoped
    send(state)
    assert card_signal_projections([card])[card.id]
    with DbSession.use(readonly=False) as db:
        policy = AppGovernancePolicy(scope_key="global", mode="disabled")
        db.insert(policy)
    assert card_signal_projections([card]) == {}
    with DbSession.use(readonly=False) as db:
        policy.mode = "approved_only"
        db.update(policy)
    assert card_signal_projections([card])[card.id]
