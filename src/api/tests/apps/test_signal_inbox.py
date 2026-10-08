# ruff: noqa: F811
"""Native board visibility, occurrence grouping and current resource authority."""

import pytest
from langboard.apps.GitHubManifest import GitHubManifestUnavailable
from langboard.apps.SignalInbox import list_board_signals
from langboard_shared.core.db import DbSession
from langboard_shared.domain.services import DomainService
from test_card_signal_projection import scoped  # noqa: F401
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
