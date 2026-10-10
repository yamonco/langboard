# ruff: noqa: F811
"""Explicit deployment card evidence under actual current storage and visibility gates."""

from copy import copy
from uuid import uuid4
import pytest
from langboard.apps.CardSignal import CardSignalConflict, bind_check, read_checks, unlink_check
from langboard.apps.DokploySignal import normalize_deployment
from langboard.apps.GitHubManifest import GitHubManifestUnavailable
from langboard_shared.core.db import DbSession, SqlBuilder
from langboard_shared.domain.models import (
    AppConnection,
    AppResourceBinding,
    AppSignal,
    BoardAppBinding,
    Card,
    CardAppSignalBinding,
    SecretReference,
)
from langboard_shared.domain.services.AppSignalProjection import card_signal_projections
from test_dokploy_connection import setup  # noqa: F401
from test_dokploy_signal import selected  # noqa: F401
from test_github_signal import board, secrets  # noqa: F401
from test_signal_inbox import deployment_inbox, dokploy_inbox  # noqa: F401


@pytest.fixture
def deployment_card(dokploy_inbox):
    service, board, *_ = dokploy_inbox[0]
    with DbSession.use(readonly=False) as db:
        board[4].actions = ["read", "update", "card_update"]
        db.update(board[4])
        card = Card(
            project_id=board[2].id,
            project_column_id=board[5][0].id,
            title="Deployment evidence",
            visibility="SHARED",
            last_change_seq=7,
        )
        db.insert(card)
        resource = db.exec(SqlBuilder.select.table(AppResourceBinding)).first()
    return dokploy_inbox, card, resource


def occurrence(state, status="done", time="2026-10-08T10:01:00Z", **updates):
    selected, _, resource = state
    row = {**selected[0][4]["rows"][0], "status": status, **updates}
    if status == "running":
        row["createdAt"] = time
        if row.get("startedAt"):
            row["startedAt"] = time
    else:
        row["finishedAt"] = time
    with DbSession.use(readonly=False) as db:
        signal = AppSignal(
            resource_id=resource.id, **normalize_deployment(row, resource.resource_type, resource.external_resource_id)
        )
        # The collector owns deduplication; distinct fixture arrivals keep explicit identities.
        signal.event_id = uuid4().hex
        db.insert(signal)
    return signal


def args(state, signal):
    selected, card, _ = state
    service, board, *_ = selected[0]
    return (
        service,
        board[1],
        board[2].get_uid(),
        card.get_uid(),
        selected[1]["connection_uid"],
        selected[2]["resource_uid"],
        signal.get_uid(),
    )


def projection(state):
    selected, card, _ = state
    service, board, *_ = selected[0]
    return read_checks(service, board[1], board[2].get_uid(), card.get_uid())


def test_deployment_lifecycle_conflict_stale_unavailable_and_no_provider_io(deployment_card, monkeypatch):
    from langboard.apps import DokploySignal

    state = deployment_card
    selected, card, resource = state
    signal = occurrence(state, "running", "2026-10-08T10:00:00Z")

    def forbidden(*args, **kwargs):
        raise AssertionError("Binding/projection must never call the provider")

    monkeypatch.setattr(DokploySignal, "read_json", forbidden)
    bound = bind_check(*args(state, signal), 7, None)
    entry = projection(state)["items"][0]
    assert entry["state"] == "queued" and entry["event_type"] == "deployment.queued"
    assert entry["provider"] == "dokploy" and entry["commit_sha"] == ""
    assert entry["resource_name"] in {"API", "Stack"} and entry["resource_type"] == resource.resource_type
    assert deployment_inbox(selected)["items"] == []
    occurrence(state, "running", "2026-10-08T10:00:10Z", startedAt="2026-10-08T10:00:10Z")
    assert projection(state)["items"][0]["state"] == "running"
    occurrence(state)
    assert projection(state)["items"][0]["state"] == "passed"
    occurrence(state, "error", "2026-10-08T10:00:20Z")
    assert projection(state)["items"][0]["state"] == "passed"
    occurrence(state, "error")
    entry = projection(state)["items"][0]
    assert entry["state"] == "conflict" and entry["outcome"] is None and entry["event_type"] is None
    occurrence(state, "error", "2026-10-08T10:02:00Z")
    assert projection(state)["items"][0]["state"] == "failed"
    occurrence(state, "cancelled", "2026-10-08T10:03:00Z")
    assert projection(state)["items"][0]["state"] == "cancelled"
    old = copy(card)
    with DbSession.use(readonly=False) as db:
        card.last_change_seq = 8
        db.update(card)
    assert card_signal_projections([old])[card.id][0]["state"] == "stale"
    with pytest.raises(CardSignalConflict):
        bind_check(*args(state, signal), 7, bound["revision"])
    rebound = bind_check(*args(state, signal), 8, bound["revision"])
    assert rebound["revision"] == 1 and projection(state)["items"][0]["state"] == "cancelled"
    with DbSession.use(readonly=False) as db:
        for row in db.exec(SqlBuilder.select.table(AppSignal)).all():
            db.delete(row)
    assert projection(state)["items"][0]["state"] == "unavailable"
    assert card.project_column_id == selected[0][1][5][0].id
    assert card.last_change_seq == 8


def test_deployment_unlink_replay_visibility_and_notifications(deployment_card, monkeypatch):
    from langboard_shared.publishers import CardPublisher

    state = deployment_card
    selected, card, _ = state
    service, board, *_ = selected[0]
    signal = occurrence(state)
    events = []
    monkeypatch.setattr(CardPublisher, "app_signal_changed", events.append)
    with pytest.raises(RuntimeError):
        with DbSession.atomic():
            bind_check(*args(state, signal), 7, None)
            assert events == []
            raise RuntimeError("rollback")
    assert events == []
    bound = bind_check(*args(state, signal), 7, None)
    assert events == [board[2].get_uid()]
    with pytest.raises(CardSignalConflict):
        bind_check(*args(state, signal), 7, None)
    with pytest.raises(CardSignalConflict):
        unlink_check(service, board[1], board[2].get_uid(), card.get_uid(), bound["binding_uid"], 1)
    unlinked = unlink_check(service, board[1], board[2].get_uid(), card.get_uid(), bound["binding_uid"], 0)
    assert unlinked["revision"] == 1 and not projection(state)["items"]
    assert len(deployment_inbox(selected)["items"]) == 1
    assert bind_check(*args(state, signal), 7, 1)["revision"] == 2
    with DbSession.use(readonly=False) as db:
        card.visibility = "PRIVATE"
        card.owner_user_id = 2
        card.created_by_user_id = 2
        db.update(card)
    assert len(deployment_inbox(selected)["items"]) == 1
    with pytest.raises(GitHubManifestUnavailable):
        projection(state)
    with pytest.raises(GitHubManifestUnavailable):
        bind_check(*args(state, signal), 7, 2)
    with pytest.raises(GitHubManifestUnavailable):
        unlink_check(service, board[1], board[2].get_uid(), card.get_uid(), bound["binding_uid"], 2)
    assert len(events) == 3


@pytest.mark.parametrize(
    "revocation", ["signals", "deployments", "secret", "connection", "resource", "access", "role", "actor", "disabled"]
)
def test_deployment_binding_and_projection_current_fences(deployment_card, revocation):
    state = deployment_card
    selected, _, resource = state
    service, board, *_ = selected[0]
    signal = occurrence(state)
    bound = bind_check(*args(state, signal), 7, None)
    assert projection(state)["items"][0]["state"] == "passed"
    with DbSession.use(readonly=False) as db:
        if revocation in {"signals", "deployments", "disabled"}:
            binding = db.exec(SqlBuilder.select.table(BoardAppBinding)).first()
            if revocation == "disabled":
                binding.state = "disabled"
            else:
                binding.granted_capabilities = [
                    cap for cap in binding.granted_capabilities if cap != revocation + ".read"
                ]
            db.update(binding)
        elif revocation == "secret":
            row = db.exec(SqlBuilder.select.table(SecretReference)).first()
            row.state = "revoked"
            db.update(row)
        elif revocation == "connection":
            row = db.exec(SqlBuilder.select.table(AppConnection)).first()
            row.state = "disconnected"
            db.update(row)
        elif revocation in {"resource", "access"}:
            if revocation == "resource":
                resource.is_selected = False
            else:
                resource.access_state = "revoked"
            db.update(resource)
        else:
            board[4].actions = ["read", "card_update"] if revocation == "role" else ["read", "update"]
            db.update(board[4])
    with pytest.raises(GitHubManifestUnavailable):
        bind_check(*args(state, signal), 7, bound["revision"])
    if revocation != "actor":
        assert projection(state)["items"] == []
    else:
        assert projection(state)["items"][0]["state"] == "passed"


def test_deployment_identity_negatives_and_binding_limit(deployment_card):
    state = deployment_card
    selected, card, resource = state
    signal = occurrence(state)
    with DbSession.use(readonly=False) as db:
        invalid = AppSignal(
            resource_id=resource.id,
            provider="dokploy",
            event_id="invalid-sha",
            external_id="dep-1",
            event_type="deployment.succeeded",
            commit_sha="a" * 40,
            outcome="success",
            occurred_at=signal.occurred_at,
            payload_digest="0" * 64,
        )
        db.insert(invalid)
    with pytest.raises(GitHubManifestUnavailable):
        bind_check(*args(state, invalid), 7, None)
    with pytest.raises(GitHubManifestUnavailable):
        bind_check(*args(state, signal)[:4], selected[1]["connection_uid"], card.get_uid(), signal.get_uid(), 7, None)
    with DbSession.use(readonly=False) as db:
        db.insert_all(
            [
                CardAppSignalBinding(
                    card_id=card.id,
                    resource_id=resource.id,
                    external_id=f"other-{i}",
                    commit_sha="",
                    source_change_seq=7,
                )
                for i in range(25)
            ]
        )
    with pytest.raises(CardSignalConflict):
        bind_check(*args(state, signal), 7, None)


def test_deployment_personal_connection_excludes_other_card_editors(deployment_card):
    from langboard_shared.core.types import SafeDateTime
    from langboard_shared.domain.models import ProjectAssignedUser, ProjectRole, User

    state = deployment_card
    selected, card, _ = state
    service, board, *_ = selected[0]
    signal = occurrence(state)
    with DbSession.use(readonly=False) as db:
        actor = User(
            firstname="Card",
            lastname="Editor",
            email="card-editor@example.invalid",
            password="fixture",
            activated_at=SafeDateTime.now(),
        )
        db.insert(actor)
        db.insert(ProjectAssignedUser(project_id=card.project_id, user_id=actor.id))
        role = ProjectRole(project_id=card.project_id, user_id=actor.id, actions=["read", "card_update"])
        db.insert(role)
    original = args(state, signal)
    actor_args = (service, actor, *original[2:])
    # Board editing does not transfer another user's personal connection consent.
    with pytest.raises(GitHubManifestUnavailable):
        bind_check(*actor_args, 7, None)
    bound = bind_check(*original, 7, None)
    assert read_checks(service, board[1], board[2].get_uid(), card.get_uid())["items"][0]["state"] == "passed"
    with DbSession.use(readonly=False) as db:
        board[4].actions = ["read", "card_update"]
        db.update(board[4])
    with pytest.raises(GitHubManifestUnavailable):
        bind_check(*original, 7, bound["revision"])
    assert read_checks(service, actor, board[2].get_uid(), card.get_uid())["items"] == []


@pytest.mark.parametrize("board", ["sqlite-http", "postgresql-test"], indirect=True)
def test_native_http_dokploy_attach_read_and_fail_closed(deployment_card, monkeypatch):
    import importlib
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from langboard.middlewares.ApiAuthMiddleware import ApiAuthMiddleware
    from langboard.routes.board import CardSignalApi as api
    from langboard_shared.core.db.DbEngine import DbEngine
    from langboard_shared.core.routing import AppRouter
    from langboard_shared.core.security import AuthSecurity
    from langboard_shared.Env import Env

    state = deployment_card
    selected, card, resource = state
    service, board, *_ = selected[0]
    signal = occurrence(state)
    service.close = lambda: None
    monkeypatch.setattr(DbEngine, "get_readonly_engine", DbEngine.get_main_engine)
    monkeypatch.setattr(
        importlib.import_module("langboard.middlewares.ApiAuthMiddleware"), "DomainService", lambda: service
    )
    app = FastAPI()
    app.include_router(AppRouter.api)
    app.add_middleware(ApiAuthMiddleware, routes=AppRouter.api.routes)
    for route in app.routes:
        if getattr(route, "endpoint", None) in {api.attach_card_signal, api.get_card_signals, api.unlink_card_signal}:
            for dependency in route.dependant.dependencies:
                if dependency.name == "service":
                    app.dependency_overrides[dependency.call] = lambda: service
    form = dict(
        connection_uid=selected[1]["connection_uid"],
        resource_uid=resource.get_uid(),
        signal_uid=signal.get_uid(),
        source_change_seq=7,
    )
    url = f"/board/{board[2].get_uid()}/card/{card.get_uid()}/signals"
    with TestClient(app, base_url="https://testserver") as client:
        assert client.post(url, json=form).status_code == 401
        access, refresh = AuthSecurity.authenticate(board[1].id)
        client.cookies.set(Env.REFRESH_TOKEN_NAME, refresh)
        headers = {"Authorization": f"Bearer {access}"}
        result = client.post(url, json=form, headers=headers)
        assert result.status_code == 200, result.text
        assert client.get(url, headers=headers).json()["items"][0]["state"] == "passed"
        assert client.post(url, json=form, headers=headers).status_code == 409
        with DbSession.use(readonly=False) as db:
            binding = db.exec(SqlBuilder.select.table(BoardAppBinding)).first()
            binding.granted_capabilities = ["signals.read"]
            db.update(binding)
        assert client.post(url, json={**form, "expected_revision": 0}, headers=headers).status_code == 404
        assert client.get(url, headers=headers).json()["items"] == []
        # Unlink is local cleanup and remains possible after provider authority revocation.
        unlink = url + "/" + result.json()["binding_uid"] + "/unlink"
        assert client.post(unlink, json={"expected_revision": 0}, headers=headers).status_code == 200
