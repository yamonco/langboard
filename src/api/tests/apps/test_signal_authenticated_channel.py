# ruff: noqa: F811
"""Native session and explicit API transport preserve PRIVATE signal authority."""

import importlib
import jwt
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from langboard.apps.CardSignal import bind_check, list_card_resources, read_checks, unlink_check
from langboard.apps.GitHubManifest import GitHubManifestUnavailable
from langboard.apps.SignalInbox import list_board_signals
from langboard.middlewares.ApiAuthMiddleware import ApiAuthMiddleware
from langboard.routes.board.CardSignalApi import (
    attach_card_signal,
    get_card_signal_resources,
    get_card_signals,
    unlink_card_signal,
)
from langboard.routes.board.SignalInboxApi import get_signal_inbox
from langboard_shared.core.db import DbSession
from langboard_shared.core.db.DbEngine import DbEngine
from langboard_shared.core.routing import AppRouter
from langboard_shared.core.security import AuthSecurity
from langboard_shared.core.security.CollaborationChannel import CollaborationChannel
from langboard_shared.Env import Env
from test_card_signal_projection import scoped  # noqa: F401
from test_github_signal import board, installation, lifecycle, secrets, signal_storage  # noqa: F401
from test_signal_card_creation import active_card, creation_scope  # noqa: F401


@pytest.mark.parametrize("board", ["sqlite-http"], indirect=True)
def test_private_signal_native_session_flow_and_api_spoof_denial(creation_scope, monkeypatch):
    state = creation_scope
    service, board, connection_uid, resource, signal_uid, *_ = state
    card, binding = active_card(state, "PRIVATE", board[1].id)
    service.close = lambda: None
    monkeypatch.setattr(DbEngine, "get_readonly_engine", DbEngine.get_main_engine)
    monkeypatch.setattr(
        importlib.import_module("langboard.middlewares.ApiAuthMiddleware"), "DomainService", lambda: service
    )
    app = FastAPI()
    app.include_router(AppRouter.api)
    app.add_middleware(ApiAuthMiddleware, routes=AppRouter.api.routes)
    for route in app.routes:
        if getattr(route, "endpoint", None) in {
            get_card_signals,
            get_card_signal_resources,
            attach_card_signal,
            unlink_card_signal,
            get_signal_inbox,
        }:
            for dependency in route.dependant.dependencies:
                if dependency.name == "service":
                    app.dependency_overrides[dependency.call] = lambda: service
    url = f"/board/{board[2].get_uid()}/card/{card.get_uid()}/signals"
    inbox = f"/board/{board[2].get_uid()}/signals/inbox"
    unlink = f"{url}/{binding.get_uid()}/unlink"
    form = dict(
        connection_uid=connection_uid,
        resource_uid=resource.get_uid(),
        signal_uid=signal_uid,
        source_change_seq=7,
        expected_revision=0,
    )
    with TestClient(app, base_url="https://testserver") as client:
        assert client.get(url).status_code == 401
        access, refresh = AuthSecurity.authenticate(board[1].id)
        client.cookies.set(Env.REFRESH_TOKEN_NAME, refresh)
        headers = {"Authorization": f"Bearer {access}"}
        read = client.get(url, headers=headers)
        assert read.status_code == 200, read.text
        assert read.json()["bindings"] == [{"binding_uid": binding.get_uid(), "revision": 0}]
        assert read.json()["items"][0]["state"] == "passed"
        resources = client.get(url + "/resources", headers=headers)
        assert resources.status_code == 200, resources.text
        if resource.resource_type == "repository":
            assert resources.json()["items"][0]["uid"] == resource.get_uid()
        else:
            assert resources.json()["items"] == []  # Existing GitHub resource picker contract.
        assert client.get(inbox, headers=headers).json()["items"] == []
        result = client.post(unlink, json={"expected_revision": 0}, headers=headers)
        assert result.status_code == 200 and result.json()["revision"] == 1, result.text
        assert client.get(inbox, headers=headers).json()["items"][0]["signal_uid"] == signal_uid
        result = client.post(url, json={**form, "expected_revision": 1}, headers=headers)
        assert result.status_code == 200 and result.json()["revision"] == 2, result.text
        assert client.get(inbox, headers=headers).json()["items"] == []
        assert client.post(url, json={**form, "expected_revision": 1}, headers=headers).status_code == 409
        for name in ("channel", "visibility_channel", "collaboration_channel"):
            assert client.post(url, json={**form, name: "human_ui"}, headers=headers).status_code in {400, 422}
            assert client.post(
                unlink, json={"expected_revision": 2, name: "human_ui"}, headers=headers
            ).status_code in {400, 422}
        # A validated internal API token remains Api even with a session cookie and client hints.
        payload = {**AuthSecurity.decode_access_token(access), "internal": True}
        api_token = jwt.encode(payload, Env.JWT_SECRET_KEY, algorithm=Env.JWT_ALGORITHM)
        api_headers = {"X-Api-Token": api_token, "X-Collaboration-Channel": "human_ui", "Collaboration-Channel": "mcp"}
        for target in (url, url + "/resources"):
            assert client.get(target, headers=api_headers, params={"channel": "human_ui"}).status_code == 404
        assert client.post(url, json={**form, "expected_revision": 2}, headers=api_headers).status_code == 404
        assert client.post(unlink, json={"expected_revision": 2}, headers=api_headers).status_code == 404
        assert client.get(inbox, headers=api_headers).json()["items"][0]["signal_uid"] == signal_uid
        # The board owner is a different authenticated actor; private links remain hidden.
        other_access, other_refresh = AuthSecurity.authenticate(board[2].owner_id)
        client.cookies.set(Env.REFRESH_TOKEN_NAME, other_refresh)
        other_headers = {"Authorization": f"Bearer {other_access}", "X-Collaboration-Channel": "human_ui"}
        for target in (url, url + "/resources"):
            assert client.get(target, headers=other_headers).status_code == 404
        assert client.post(url, json={**form, "expected_revision": 2}, headers=other_headers).status_code == 404
        assert client.post(unlink, json={"expected_revision": 2}, headers=other_headers).status_code == 404
        assert client.get(inbox, headers=other_headers).json()["items"][0]["signal_uid"] == signal_uid


@pytest.mark.parametrize("board", ["sqlite-http"], indirect=True)
@pytest.mark.parametrize("channel", [CollaborationChannel.HumanUI, CollaborationChannel.Mcp])
def test_private_owner_helper_channel_and_api_default_compatibility(creation_scope, channel):
    service, board, connection_uid, resource, signal_uid, *_ = creation_scope
    card, binding = active_card(creation_scope, "PRIVATE", board[1].id)
    args = service, board[1], board[2].get_uid()
    assert read_checks(*args, card.get_uid(), channel=channel)["bindings"]
    resources = list_card_resources(*args, card.get_uid(), channel=channel)
    if resource.resource_type == "repository":
        assert resources["items"]
    else:
        assert resources["items"] == []
    assert list_board_signals(*args, channel=channel)["items"] == []
    for helper in (read_checks, list_card_resources):
        with pytest.raises(GitHubManifestUnavailable):
            helper(*args, card.get_uid())
    with pytest.raises(GitHubManifestUnavailable):
        unlink_check(*args, card.get_uid(), binding.get_uid(), 0)
    with pytest.raises(GitHubManifestUnavailable):
        bind_check(*args, card.get_uid(), connection_uid, resource.get_uid(), signal_uid, 7, 0)
    assert list_board_signals(*args)["items"][0]["signal_uid"] == signal_uid
    unlink_check(*args, card.get_uid(), binding.get_uid(), 0, channel=channel)
    result = bind_check(
        *args, card.get_uid(), connection_uid, resource.get_uid(), signal_uid, 7, 1, visibility_channel=channel
    )
    assert result["revision"] == 2
    with DbSession.use(readonly=False) as db:
        card.owner_user_id = card.created_by_user_id = board[2].owner_id
        db.update(card)
    assert list_board_signals(*args, channel=channel)["items"][0]["signal_uid"] == signal_uid
    with pytest.raises(GitHubManifestUnavailable):
        read_checks(*args, card.get_uid(), channel=channel)
