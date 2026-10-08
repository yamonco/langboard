# ruff: noqa: F811
"""Native board visibility, occurrence grouping and current resource authority."""

import pytest
from langboard.apps.GitHubManifest import GitHubManifestUnavailable
from langboard.apps.SignalInbox import list_board_signals
from langboard_shared.core.db import DbSession
from langboard_shared.domain.services import DomainService
from test_card_signal_projection import scoped  # noqa: F401
from test_dokploy_connection import setup  # noqa: F401
from test_dokploy_signal import selected  # noqa: F401
from test_github_signal import board, installation, lifecycle, secrets, send, signal_storage  # noqa: F401


def inbox(scoped, after=None):
    state, _, _, _ = scoped
    state[0].card = DomainService().card
    return list_board_signals(state[0], state[1][1], state[1][2].get_uid(), after)


def test_inbox_hides_visible_links_but_not_private_link_existence(scoped):
    state, card, binding, _ = scoped
    send(state)
    assert inbox(scoped)["items"] == []
    with DbSession.use(readonly=False) as db:
        card.visibility = "PRIVATE"
        card.owner_user_id = state[1][1].id
        card.created_by_user_id = state[1][1].id
        db.update(card)
    assert len(inbox(scoped)["items"]) == 1
    with DbSession.use(readonly=False) as db:
        card.visibility = "SHARED"
        card.owner_user_id = None
        db.update(card)
        binding.is_enabled = False
        db.update(binding)
    assert len(inbox(scoped)["items"]) == 1


def test_inbox_latest_occurrence_conflict_and_bounded_pages(scoped):
    state, _, binding, _ = scoped
    with DbSession.use(readonly=False) as db:
        binding.is_enabled = False
        db.update(binding)
    send(state)
    state[5]["check_run"].update(conclusion="failure", completed_at="2026-10-08T02:00:00Z")
    send(state)
    state[5]["check_run"].update(conclusion="success", completed_at="2026-10-08T01:00:00Z")
    send(state)
    rows = inbox(scoped)["items"]
    assert len(rows) == 1 and rows[0]["outcome"] == "failure" and not rows[0]["conflict"]
    state[5]["check_run"].update(completed_at="2026-10-08T02:00:00Z")
    send(state)
    row = inbox(scoped)["items"][0]
    assert row["conflict"] and row["outcome"] is None
    assert "payload_digest" not in row and "event_id" not in row
    for external_id in range(100, 130):
        state[5]["check_run"].update(id=external_id)
        send(state)
    first = inbox(scoped)
    second = inbox(scoped, first["next_cursor"])
    assert len(first["items"]) == 25 and len(second["items"]) == 6 and second["next_cursor"] is None
    assert not ({row["signal_uid"] for row in first["items"]} & {row["signal_uid"] for row in second["items"]})
    with pytest.raises(ValueError):
        inbox(scoped, "../invalid")


@pytest.mark.parametrize("revocation", ["resource", "secret", "reader"])
def test_inbox_current_revocation(scoped, revocation):
    state, _, binding, _ = scoped
    with DbSession.use(readonly=False) as db:
        binding.is_enabled = False
        db.update(binding)
    send(state)
    assert len(inbox(scoped)["items"]) == 1
    if revocation == "secret":
        state[0].secret_reference.revoke(state[1][1], state[2].credential_reference, 0)
    else:
        with DbSession.use(readonly=False) as db:
            target = state[4] if revocation == "resource" else state[1][1]
            if revocation == "resource":
                target.is_selected = False
            else:
                target.activated_at = None
            db.update(target)
    if revocation == "reader":
        with pytest.raises(GitHubManifestUnavailable):
            inbox(scoped)
    else:
        assert inbox(scoped)["items"] == []


@pytest.mark.parametrize("board", ["sqlite-http", "postgresql-test"], indirect=True)
def test_inbox_native_http_auth_cursor_and_board_scope(scoped, monkeypatch):
    import importlib
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from langboard.middlewares.ApiAuthMiddleware import ApiAuthMiddleware
    from langboard.routes.board.SignalInboxApi import get_signal_inbox
    from langboard_shared.core.db.DbEngine import DbEngine
    from langboard_shared.core.routing import AppRouter
    from langboard_shared.core.security import AuthSecurity
    from langboard_shared.Env import Env

    state, _, binding, _ = scoped
    service = state[0]
    service.card = DomainService().card
    service.close = lambda: None
    with DbSession.use(readonly=False) as db:
        binding.is_enabled = False
        db.update(binding)
    send(state)
    monkeypatch.setattr(DbEngine, "get_readonly_engine", DbEngine.get_main_engine)
    monkeypatch.setattr(
        importlib.import_module("langboard.middlewares.ApiAuthMiddleware"), "DomainService", lambda: service
    )
    app = FastAPI()
    app.include_router(AppRouter.api)
    app.add_middleware(ApiAuthMiddleware, routes=AppRouter.api.routes)
    for route in app.routes:
        if getattr(route, "endpoint", None) == get_signal_inbox:
            for dependency in route.dependant.dependencies:
                if dependency.name == "service":
                    app.dependency_overrides[dependency.call] = lambda: service
    url = f"/board/{state[1][2].get_uid()}/signals/inbox"
    with TestClient(app, base_url="https://testserver") as client:
        assert client.get(url).status_code == 401
        access, refresh = AuthSecurity.authenticate(state[1][1].id)
        client.cookies.set(Env.REFRESH_TOKEN_NAME, refresh)
        headers = {"Authorization": f"Bearer {access}"}
        result = client.get(url, headers=headers)
        assert result.status_code == 200, result.text
        assert len(result.json()["items"]) == 1
        assert client.get(url, params={"after": "../invalid"}, headers=headers).status_code == 400
        assert client.get(url.replace(state[1][2].get_uid(), "nonexistent"), headers=headers).status_code == 404


@pytest.fixture
def dokploy_inbox(selected):
    from langboard_shared.core.db.DbEngine import DbEngine
    from langboard_shared.domain.models import (
        Card,
        CardAppSignalBinding,
        EmployeeMembershipPolicy,
        ScimGroup,
        ScimGroupMember,
        UserIdentityLink,
    )

    service, board, *_ = selected[0]
    engine = DbEngine.get_main_engine()
    for model in (Card, CardAppSignalBinding, EmployeeMembershipPolicy, ScimGroup, ScimGroupMember, UserIdentityLink):
        model.__table__.create(engine, checkfirst=True)
    domain = DomainService()
    service.card = domain.card
    try:
        yield selected
    finally:
        domain.close()


def deployment_inbox(selected, after=None):
    service, board, *_ = selected[0]
    return list_board_signals(service, board[1], board[2].get_uid(), after)


def test_dokploy_lifecycle_conflict_and_safe_contract(dokploy_inbox):
    from test_dokploy_signal import refresh

    row = dokploy_inbox[0][4]["rows"][0]
    row["status"] = "running"
    refresh(dokploy_inbox)
    entry = deployment_inbox(dokploy_inbox)["items"][0]
    assert entry["event_type"] == "deployment.queued" and entry["outcome"] == "queued"
    assert entry["can_bind_card"] and entry["commit_sha"] == ""
    assert entry["resource_type"] in {"application", "compose"}
    assert entry["resource_name"] == ("API" if entry["resource_type"] == "application" else "Stack")
    assert "private" not in str(entry)
    row["startedAt"] = "2026-10-08T10:00:10Z"
    refresh(dokploy_inbox)
    assert deployment_inbox(dokploy_inbox)["items"][0]["event_type"] == "deployment.started"
    row["status"] = "done"
    refresh(dokploy_inbox)
    assert deployment_inbox(dokploy_inbox)["items"][0]["outcome"] == "success"
    # Late arrival cannot replace a later occurrence.
    row["status"] = "running"
    refresh(dokploy_inbox)
    assert deployment_inbox(dokploy_inbox)["items"][0]["outcome"] == "success"
    row["status"] = "error"
    refresh(dokploy_inbox)
    entry = deployment_inbox(dokploy_inbox)["items"][0]
    assert entry["conflict"] and entry["outcome"] is None
    row.update(status="cancelled", finishedAt="2026-10-08T10:02:00Z")
    refresh(dokploy_inbox)
    entry = deployment_inbox(dokploy_inbox)["items"][0]
    assert entry["event_type"] == "deployment.cancelled" and entry["outcome"] == "cancelled"
    assert not entry["conflict"]
    assert not {"payload_digest", "event_id", "approval", "verified", "logPath", "errorMessage"} & entry.keys()


@pytest.mark.parametrize(
    "revocation", ["signals", "deployments", "disabled", "secret", "role", "resource", "access", "connection", "member"]
)
def test_dokploy_inbox_current_authority(dokploy_inbox, revocation):
    from langboard_shared.core.db import SqlBuilder
    from langboard_shared.domain.models import AppConnection, AppResourceBinding, BoardAppBinding, SecretReference
    from test_dokploy_signal import refresh

    refresh(dokploy_inbox)
    assert len(deployment_inbox(dokploy_inbox)["items"]) == 1
    board = dokploy_inbox[0][1]
    with DbSession.use(readonly=False) as db:
        binding = db.exec(SqlBuilder.select.table(BoardAppBinding)).first()
        resource = db.exec(SqlBuilder.select.table(AppResourceBinding)).first()
        connection = db.exec(SqlBuilder.select.table(AppConnection)).first()
        if revocation in {"signals", "deployments"}:
            binding.granted_capabilities = [cap for cap in binding.granted_capabilities if cap != revocation + ".read"]
            db.update(binding)
        elif revocation == "disabled":
            binding.state = "disabled"
            db.update(binding)
        elif revocation == "secret":
            secret = db.exec(SqlBuilder.select.table(SecretReference)).first()
            secret.state = "revoked"
            db.update(secret)
        elif revocation == "role":
            board[4].actions = ["read"]
            db.update(board[4])
        elif revocation == "member":
            db.delete(board[3])
        elif revocation in {"resource", "access"}:
            if revocation == "resource":
                resource.is_selected = False
            else:
                resource.access_state = "revoked"
            db.update(resource)
        else:
            connection.state = "disconnected"
            db.update(connection)
    if revocation == "member":
        with pytest.raises(GitHubManifestUnavailable):
            deployment_inbox(dokploy_inbox)
    else:
        assert deployment_inbox(dokploy_inbox)["items"] == []


def test_dokploy_inbox_bounded_pages_board_provider_and_resource_fences(dokploy_inbox):
    from langboard_shared.core.db import SqlBuilder
    from langboard_shared.domain.models import AppResourceBinding, AppSignal, BoardAppBinding
    from test_dokploy_signal import refresh

    state = dokploy_inbox[0][4]
    template = state["rows"][0]
    refresh(dokploy_inbox)
    with DbSession.use(readonly=False) as db:
        from langboard.apps.DokploySignal import normalize_deployment

        resource = db.exec(SqlBuilder.select.table(AppResourceBinding)).first()
        db.insert_all(
            [
                AppSignal(
                    resource_id=resource.id,
                    **normalize_deployment(
                        {**template, "deploymentId": f"dep-page-{number}"},
                        resource.resource_type,
                        resource.external_resource_id,
                    ),
                )
                for number in range(30)
            ]
        )
        binding = db.exec(SqlBuilder.select.table(BoardAppBinding)).first()
        foreign_binding = BoardAppBinding(
            project_id=11, app_key="dokploy", state="enabled", granted_capabilities=binding.granted_capabilities
        )
        db.insert(foreign_binding)
        foreign = AppResourceBinding(
            board_binding_id=foreign_binding.id,
            connection_id=resource.connection_id,
            resource_type=resource.resource_type,
            external_resource_id="foreign",
            access_state="granted",
        )
        parent = AppResourceBinding(
            board_binding_id=binding.id,
            connection_id=resource.connection_id,
            resource_type="environment",
            external_resource_id="env",
            access_state="granted",
        )
        db.insert(foreign)
        db.insert(parent)
        for number, (target, provider, event_type, sha) in enumerate(
            (
                (foreign, "dokploy", "deployment.succeeded", ""),
                (parent, "dokploy", "deployment.succeeded", ""),
                (resource, "github", "check.completed", "a" * 40),
                (resource, "dokploy", "check.completed", ""),
                (resource, "dokploy", "deployment.succeeded", "a" * 40),
            )
        ):
            db.insert(
                AppSignal(
                    resource_id=target.id,
                    provider=provider,
                    event_type=event_type,
                    external_id="excluded",
                    commit_sha=sha,
                    occurred_at="2026-10-08T12:00:00.000000+00:00",
                    outcome="success",
                    event_id=f"excluded-{number}",
                    payload_digest="0" * 64,
                )
            )
    first = deployment_inbox(dokploy_inbox)
    second = deployment_inbox(dokploy_inbox, first["next_cursor"])
    assert len(first["items"]) == 25 and len(second["items"]) == 6 and second["next_cursor"] is None
    assert "excluded" not in str(first) + str(second)
    assert not ({row["signal_uid"] for row in first["items"]} & {row["signal_uid"] for row in second["items"]})
    with pytest.raises(ValueError):
        deployment_inbox(dokploy_inbox, foreign.get_uid())


def test_github_commit_identity_remains_bindable(scoped):
    state, _, binding, _ = scoped
    with DbSession.use(readonly=False) as db:
        binding.is_enabled = False
        db.update(binding)
    send(state)
    state[5]["check_run"].update(head_sha="b" * 40)
    send(state)
    entries = inbox(scoped)["items"]
    assert {entry["commit_sha"] for entry in entries} == {"a" * 40, "b" * 40}
    assert all(entry["can_bind_card"] for entry in entries)


def test_dokploy_deployment_identity_is_resource_scoped_and_visible_links_consumed(dokploy_inbox):
    from langboard_shared.core.db import SqlBuilder
    from langboard_shared.domain.models import (
        AppResourceBinding,
        AppSignal,
        BoardAppBinding,
        Card,
        CardAppSignalBinding,
    )
    from test_dokploy_signal import refresh

    refresh(dokploy_inbox)
    board = dokploy_inbox[0][1]
    with DbSession.use(readonly=False) as db:
        original = db.exec(SqlBuilder.select.table(AppResourceBinding)).first()
        original_signal = db.exec(SqlBuilder.select.table(AppSignal)).first()
        sibling = AppResourceBinding(
            board_binding_id=original.board_binding_id,
            connection_id=original.connection_id,
            resource_type=original.resource_type,
            external_resource_id="second-resource",
            access_state="granted",
        )
        db.insert(sibling)
        db.insert(
            AppSignal(
                resource_id=sibling.id,
                provider="dokploy",
                event_type="deployment.failed",
                external_id="dep-1",
                commit_sha="",
                occurred_at=original_signal.occurred_at,
                outcome="failure",
                event_id="second-resource",
                payload_digest="0" * 64,
            )
        )
        card = Card(
            project_id=board[2].id, project_column_id=board[5][0].id, title="No deployment binding", visibility="SHARED"
        )
        db.insert(card)
        # Enabled links consume their exact resource/deployment identity.
        db.insert(
            CardAppSignalBinding(
                card_id=card.id, resource_id=original.id, external_id="dep-1", commit_sha="", source_change_seq=0
            )
        )
    entries = deployment_inbox(dokploy_inbox)["items"]
    assert len(entries) == 1 and entries[0]["outcome"] == "failure"
    assert all(not entry["conflict"] and entry["can_bind_card"] for entry in entries)
    with DbSession.use(readonly=False) as db:
        current = db.exec(SqlBuilder.select.table(BoardAppBinding)).first()
        assert not current.stage_transitions_enabled and current.workflow_mapping == {}
        assert db.exec(SqlBuilder.select.table(Card)).first().last_change_seq == 0


def test_inbox_resource_name_fallback_and_bound():
    from types import SimpleNamespace
    from langboard.apps.SignalInbox import _resource_name

    assert (
        _resource_name(SimpleNamespace(resource_path=[], external_resource_id="deployment-resource"))
        == "deployment-resource"
    )
    assert (
        _resource_name(SimpleNamespace(resource_path=[{"name": "x" * 250}], external_resource_id="fallback"))
        == "x" * 200
    )
    assert (
        _resource_name(SimpleNamespace(resource_path=[{"name": {"env": "private"}}], external_resource_id="fallback"))
        == "fallback"
    )
