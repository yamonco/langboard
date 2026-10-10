# ruff: noqa: F811
"""Real authority, secret storage and bounded HTTP; no provider mutation."""

import json
import httpx
import pytest
from langboard.apps import DokployConnection as dk
from langboard.apps import DokployNotificationConfig as probe
from langboard.apps import DokployWebhook as webhook
from langboard_shared.core.db import DbSession, SqlBuilder
from langboard_shared.core.db.DbEngine import DbEngine
from langboard_shared.domain.models import (
    AppConnection,
    AppResourceBinding,
    AppSignal,
    BoardAppBinding,
    Card,
    DokployNotificationReceipt,
    DokployWebhookBinding,
    SecretReference,
    User,
)
from langboard_shared.domain.services.factory.SecretReferenceService_test import secrets  # noqa: F401
from langboard_shared.domain.services.factory.WorkflowStageService_app_test import board  # noqa: F401
from pydantic import SecretStr
from test_dokploy_connection import setup  # noqa: F401
from test_dokploy_webhook import configured  # noqa: F401


@pytest.fixture
def ready(configured, monkeypatch):
    Card.__table__.create(DbEngine.get_main_engine(), checkfirst=True)
    with DbSession.use(readonly=False) as db:
        db.insert(
            Card(
                project_id=configured[0][1][2].id,
                project_column_id=configured[0][1][5][0].id,
                title="Protected existing card",
                order=0,
            )
        )
        config = db.exec(SqlBuilder.select.table(DokployWebhookBinding)).first()
        config.notification_id = "notification-1"
        db.update(config)
    callback = "https://receiver.example.invalid/proxy" + configured[3]["receiver_path"]
    state = {
        "data": {
            "notificationId": "notification-1",
            "notificationType": "custom",
            "appDeploy": True,
            "appBuildError": True,
            "customId": "custom-1",
            "custom": {
                "customId": "custom-1",
                "endpoint": callback,
                "headers": {"aUtHoRiZaTiOn": "Bearer receiver-token"},
            },
        },
        "after": None,
        "failure": None,
        "management_token": "fixture-api-key",
    }
    calls = []
    # Preserve native transport configuration and real HTTP streaming behavior.
    # setup wrapped Client for onboarding; use the actual class for this fixed endpoint.
    original_client = httpx._client.Client

    def external(request):
        assert not DbSession.has_active_transaction()
        calls.append(request)
        assert request.method == "GET" and request.url.path == "/api/notification.one"
        assert request.url.host == "deploy.example.invalid"
        assert dict(request.url.params) == {"notificationId": "notification-1"}
        assert request.headers["x-api-key"] == state["management_token"]
        if state["after"]:
            state["after"]()
        if state["failure"] == "timeout":
            raise httpx.ReadTimeout("private credential", request=request)
        if state["failure"] == "oversize":
            return httpx.Response(200, content=b" " * 262145)
        if state["failure"] == "invalid-json":
            return httpx.Response(200, content=b"private invalid")
        if state["failure"] == "deep-json":
            return httpx.Response(200, content=b"[" * 50000 + b"0" + b"]" * 50000)
        if state["failure"]:
            return httpx.Response(state["failure"], headers={"Location": callback})
        return httpx.Response(200, json=state["data"])

    monkeypatch.setattr(
        httpx, "Client", lambda **kwargs: original_client(transport=httpx.MockTransport(external), **kwargs)
    )
    return configured, callback, state, calls


def verify(ready):
    configured, callback, *_ = ready
    setup, conn, _, config = configured
    return probe.verify(
        setup[0],
        setup[1][1],
        setup[1][2].get_uid(),
        conn["connection_uid"],
        conn["revision"],
        config["binding_revision"],
        1,
        callback,
    )


def inventory():
    with DbSession.use(readonly=False) as db:
        return {
            model.__name__: [row.model_dump() for row in db.exec(SqlBuilder.select.table(model)).all()]
            for model in (
                AppConnection,
                AppResourceBinding,
                BoardAppBinding,
                Card,
                DokployWebhookBinding,
                DokployNotificationReceipt,
                AppSignal,
            )
        }


def test_match_ephemeral_safe_contract(ready, monkeypatch):
    protected = (
        Card,
        AppSignal,
        DokployNotificationReceipt,
        DokployWebhookBinding,
        AppConnection,
        BoardAppBinding,
        AppResourceBinding,
    )
    for operation in ("insert", "update", "delete"):
        original = getattr(DbSession, operation)

        def guard(db, record, *args, _original=original, **kwargs):
            assert not isinstance(record, protected), "Verification attempted state mutation"
            return _original(db, record, *args, **kwargs)

        monkeypatch.setattr(DbSession, operation, guard)
    before = inventory()
    result = verify(ready)
    assert result["provider_config"] == "matched" and all(result["checks"].values())
    assert set(result) == {
        "provider_config",
        "checked_at",
        "config_revision",
        "connection_revision",
        "binding_revision",
        "checks",
    }
    assert result["config_revision"] == 1 and result["checked_at"].endswith("+00:00")
    assert not any(value in json.dumps(result) for value in ("receiver-token", "fixture-api-key", "example.invalid"))
    assert inventory() == before and len(ready[3]) == 1
    configured = ready[0]
    assert (
        webhook.health(
            configured[0][0], configured[0][1][1], configured[0][1][2].get_uid(), configured[1]["connection_uid"]
        )["provider_config"]
        == "unknown"
    )


@pytest.mark.parametrize(
    "field,value,check",
    [
        ("notificationId", "wrong", "notification_id"),
        ("notificationType", [], "custom_type"),
        ("appDeploy", 1, "build_success"),
        ("appBuildError", "true", "build_error"),
        ("custom", None, "endpoint"),
        ("custom", [], "authorization"),
    ],
)
def test_truthful_mismatch(ready, field, value, check):
    ready[2]["data"][field] = value
    result = verify(ready)
    assert result["provider_config"] == "mismatch" and result["checks"][check] is False


@pytest.mark.parametrize(
    "headers",
    [
        None,
        [],
        {"Authorization": "Bearer wrong"},
        {"Authorization": "Bearer receiver-token", "authorization": "Bearer receiver-token"},
        {"Authorization": "Bearer receiver-token", "X": 1},
        {"Authorization": "Bearer receiver-token", "X": "bad\nvalue"},
    ],
)
def test_malformed_headers(ready, headers):
    ready[2]["data"]["custom"]["headers"] = headers
    assert verify(ready)["checks"]["authorization"] is False


@pytest.mark.parametrize("failure", [302, 401, 403, 404, 500, "timeout", "oversize", "invalid-json"])
def test_unavailable_retains_state(ready, failure):
    ready[2]["failure"] = failure
    before = inventory()
    assert verify(ready)["checks"] is None
    assert verify(ready)["provider_config"] == "unavailable"
    assert inventory() == before


def mutate(ready, failure):
    configured = ready[0]
    with DbSession.use(readonly=False) as db:
        if failure == "role":
            row = configured[0][1][4]
            row.actions = ["read"]
        elif failure == "inactive":
            row = db.exec(SqlBuilder.select.table(User).where(User.id == configured[0][1][1].id)).first()
            row.activated_at = None
        elif failure in {"owner", "connection"}:
            row = db.exec(SqlBuilder.select.table(AppConnection)).first()
            if failure == "owner":
                row.owner_id = 2
            else:
                row.state = "disconnected"
        elif failure == "binding":
            row = db.exec(SqlBuilder.select.table(BoardAppBinding)).first()
            row.granted_capabilities = []
        elif failure in {"resource", "resource_revision"}:
            row = db.exec(SqlBuilder.select.table(AppResourceBinding)).first()
            if failure == "resource":
                row.is_selected = False
            else:
                row.access_revision += 1
        elif failure in {"disabled", "missing", "config_revision", "binding_revision"}:
            row = db.exec(SqlBuilder.select.table(DokployWebhookBinding)).first()
            if failure == "disabled":
                row.state = "disabled"
            elif failure == "missing":
                row.notification_id = None
            elif failure == "config_revision":
                row.config_revision += 1
            else:
                row.binding_revision = "0" * 64
        else:
            uri = configured[0][2]["uri"] if failure.startswith("management") else configured[2]["uri"]
            from langboard_shared.helpers import InfraHelper

            row = db.exec(
                SqlBuilder.select.table(SecretReference).where(
                    SecretReference.id == InfraHelper.convert_id(uri.rsplit("/", 1)[1])
                )
            ).first()
            if failure.endswith("rotation"):
                row.revision += 1
            else:
                row.state = "revoked"
        db.update(row)


FAILURES = [
    "role",
    "inactive",
    "owner",
    "connection",
    "binding",
    "resource",
    "resource_revision",
    "disabled",
    "missing",
    "config_revision",
    "binding_revision",
    "management_rotation",
    "management_revoked",
    "receiver_rotation",
    "receiver_revoked",
]


@pytest.mark.parametrize("failure", FAILURES)
@pytest.mark.parametrize("during_io", [False, True])
def test_authority_and_fences_before_and_after(ready, failure, during_io):
    from langboard_shared.domain.services.factory.SecretReferenceService import SecretReferenceUnavailable

    if failure == "management_rotation" and not during_io:
        # Rotation completed before a new explicit check uses the current key.
        # Only changes during provider I/O invalidate the captured secret revision.
        configured = ready[0]
        service, board, reference, *_ = configured[0]
        service.secret_reference.rotate(
            board[1], reference["uri"], SecretStr("current-management-key"), reference["revision"]
        )
        ready[2]["management_token"] = "current-management-key"
        assert verify(ready)["provider_config"] == "matched"
        assert len(ready[3]) == 1
        return
    if during_io:
        ready[2]["after"] = lambda: mutate(ready, failure)
    else:
        mutate(ready, failure)
    with pytest.raises((dk.DokployUnavailable, dk.DokployConflict, SecretReferenceUnavailable)):
        verify(ready)
    assert len(ready[3]) == int(during_io)


@pytest.mark.parametrize("failure", ["role", "management_rotation", "receiver_rotation", "config_revision"])
@pytest.mark.parametrize("transport_failure", ["timeout", "deep-json"])
def test_transport_failure_still_rechecks_authority(ready, failure, transport_failure):
    ready[2]["after"] = lambda: mutate(ready, failure)
    ready[2]["failure"] = transport_failure
    with pytest.raises((dk.DokployUnavailable, dk.DokployConflict)):
        verify(ready)


@pytest.mark.parametrize(
    "value",
    [
        "http://r.invalid",
        "https://u:p@r.invalid",
        "https://r.invalid/../x",
        "https://r.invalid/%2f",
        "https://r.invalid\\x",
        "https://r.invalid/?q=1",
        "https://r.invalid/#x",
        "https://r.invalid/other",
        "https://r.invalid/\n",
        "https://r.invalid/" + "x" * 2048,
    ],
)
def test_invalid_callback_never_fetches(ready, value):
    ready = ready[0], value, ready[2], ready[3]
    with pytest.raises(ValueError):
        verify(ready)
    assert ready[3] == []


@pytest.mark.parametrize("custom_id", [None, [], "wrong"])
def test_malformed_custom_relation_mismatch(ready, custom_id):
    ready[2]["data"]["custom"]["customId"] = custom_id
    assert verify(ready)["checks"]["custom_type"] is False


@pytest.mark.parametrize("board", ["sqlite-http"], indirect=True)
def test_native_authenticated_http_contract(ready, monkeypatch):
    import importlib
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from langboard.middlewares.ApiAuthMiddleware import ApiAuthMiddleware
    from langboard.routes.board import BoardDokployAppApi as api
    from langboard_shared.core.db.DbEngine import DbEngine
    from langboard_shared.core.routing import AppRouter
    from langboard_shared.core.security import AuthSecurity
    from langboard_shared.Env import Env

    configured, callback, _, calls = ready
    service = configured[0][0]
    service.close = lambda: None
    monkeypatch.setattr(DbEngine, "get_readonly_engine", DbEngine.get_main_engine)
    monkeypatch.setattr(
        importlib.import_module("langboard.middlewares.ApiAuthMiddleware"), "DomainService", lambda: service
    )
    app = FastAPI()
    app.include_router(AppRouter.api)
    for route in app.routes:
        if getattr(route, "endpoint", None) == api.verify_dokploy_webhook:
            for dependency in route.dependant.dependencies:
                if dependency.name == "service":
                    app.dependency_overrides[dependency.call] = lambda: service
    app.add_middleware(ApiAuthMiddleware, routes=AppRouter.api.routes)
    access, refresh = AuthSecurity.authenticate(configured[0][1][1].id)
    path = f"/board/{configured[0][1][2].get_uid()}/settings/apps/dokploy/connections/{configured[1]['connection_uid']}/webhook-verify"
    form = {
        "expected_revision": configured[1]["revision"],
        "expected_binding_revision": configured[3]["binding_revision"],
        "expected_config_revision": 1,
        "callback_url": callback,
    }
    with TestClient(app) as client:
        assert client.post(path, json=form).status_code == 401
        client.cookies.set(Env.REFRESH_TOKEN_NAME, refresh)
        headers = {"Authorization": "Bearer " + access}
        result = client.post(path, json=form, headers=headers)
        assert result.status_code == 200 and result.json()["provider_config"] == "matched"
        assert result.headers["Cache-Control"] == "no-store"
        for bad in ({"expected_config_revision": 0}, {"expected_config_revision": True}, {"arbitrary_url": callback}):
            assert client.post(path, json={**form, **bad}, headers=headers).status_code == 400
        assert len(calls) == 1
        assert client.post(path, json={**form, "expected_revision": "0" * 64}, headers=headers).status_code == 409
        mutate(ready, "role")
        assert client.post(path, json=form, headers=headers).status_code == 404
        assert len(calls) == 1
