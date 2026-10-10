# ruff: noqa: F811
"""Real host authority and storage with official metadata endpoint contracts."""

import json
from types import SimpleNamespace
import httpx
import pytest
from langboard.apps import DokployConnection as dk
from langboard.apps import MetadataTransport as transport
from langboard_shared.core.db import DbSession, SqlBuilder
from langboard_shared.domain.models import AppConnection, AppResourceBinding, BoardAppBinding
from langboard_shared.domain.services.factory.SecretReferenceService_test import secrets  # noqa: F401
from langboard_shared.domain.services.factory.WorkflowStageService_app_test import board  # noqa: F401
from langboard_shared.Env import Env
from pydantic import SecretStr


@pytest.fixture
def setup(secrets, monkeypatch):
    from langboard_shared.core.caching import Cache
    from langboard_shared.core.caching.InMemoryCache import InMemoryCache

    monkeypatch.setattr(Cache, "_cache", InMemoryCache())
    secret_service, board, _ = secrets
    with DbSession.use(readonly=False) as db:
        board[4].actions = ["read", "update"]
        db.update(board[4])
    service = SimpleNamespace(workflow_stage=board[0], secret_reference=secret_service)
    reference = secret_service.create(board[1], "personal", "me", "dokploy/api", SecretStr("fixture-api-key"))
    original_env = Env.get_from_env
    monkeypatch.setattr(
        Env,
        "get_from_env",
        lambda key, default=None: "https://deploy.example.invalid"
        if key == "APP_CONNECTION_ALLOWED_BASE_URLS"
        else original_env(key, default),
    )
    calls = []
    state = {"failure": None, "after": None}

    def external(request):
        calls.append(request)
        assert request.url.host == "deploy.example.invalid"
        assert request.headers["x-api-key"] == "fixture-api-key"
        assert "Authorization" not in request.headers and request.method == "GET"
        if state["after"]:
            state["after"]()
        if state["failure"] == "redirect":
            return httpx.Response(302, headers={"Location": "https://attacker.invalid"})
        if state["failure"] == "oversize":
            return httpx.Response(200, content=b" " * 262145)
        if state["failure"] == "json":
            return httpx.Response(200, content=b"no json")
        if request.url.path == "/api/project.all":
            return httpx.Response(200, json=[{"projectId": "project-1", "name": "Project", "env": "private"}])
        if request.url.path == "/api/environment.byProjectId":
            assert request.url.params["projectId"] == "project-1"
            return httpx.Response(200, json=[{"environmentId": "env-1", "name": "Production", "env": "private"}])
        assert request.url.path == "/api/environment.one" and request.url.params["environmentId"] == "env-1"
        return httpx.Response(
            200,
            json={
                "environmentId": "env-1",
                "projectId": "project-1",
                "name": "Production",
                "env": "private",
                "applications": [{"applicationId": "app-1", "name": "API", "env": "private"}],
                "compose": [{"composeId": "compose-1", "name": "Stack", "composeFile": "private"}],
            },
        )

    original_client = httpx.Client
    monkeypatch.setattr(
        transport.httpx, "Client", lambda **kwargs: original_client(transport=httpx.MockTransport(external), **kwargs)
    )
    return service, board, reference, calls, state


def connect(setup):
    service, board, reference, *_ = setup
    return dk.register_connection(
        service, board[1], board[2].get_uid(), "https://deploy.example.invalid/", reference["uri"]
    )


def test_register_and_hierarchy_return_only_safe_metadata(setup):
    service, board, _, calls, _ = setup
    connection = connect(setup)
    assert "fixture-api-key" not in json.dumps(connection) and "credential_reference" not in connection
    args = service, board[1], board[2].get_uid(), connection["connection_uid"]
    assert dk.list_connections(*args[:3])["items"] == [connection]
    assert dk.discover_resources(*args)["items"] == [{"id": "project-1", "type": "project", "name": "Project"}]
    assert dk.discover_resources(*args, "project-1")["items"] == [
        {"id": "env-1", "type": "environment", "name": "Production"}
    ]
    result = dk.discover_resources(*args, "project-1", "env-1")
    assert result["items"] == [
        {"id": "app-1", "type": "application", "name": "API"},
        {"id": "compose-1", "type": "compose", "name": "Stack"},
    ]
    assert "private" not in json.dumps(result) and result["next_cursor"] is None
    assert len(calls) == 5
    with DbSession.use(readonly=False) as db:
        assert not db.exec(SqlBuilder.select.table(AppResourceBinding)).all()
        assert not db.exec(SqlBuilder.select.table(BoardAppBinding)).all()


@pytest.mark.parametrize(
    "bad",
    [
        "http://deploy.example.invalid",
        "https://other.invalid",
        "https://user@deploy.example.invalid",
        "https://deploy.example.invalid?key=private",
    ],
)
def test_unapproved_instance_no_io(setup, bad):
    service, board, reference, calls, _ = setup
    with pytest.raises(ValueError):
        dk.register_connection(service, board[1], board[2].get_uid(), bad, reference["uri"])
    assert not calls


@pytest.mark.parametrize("failure", ["role", "rotation", "endpoint", "disconnect", "redirect", "oversize", "json"])
def test_discovery_rechecks_authority_after_io(setup, failure):
    service, board, reference, calls, state = setup
    connection = connect(setup)

    def change():
        if failure == "rotation":
            service.secret_reference.rotate(board[1], reference["uri"], SecretStr("new-key"), reference["revision"])
        else:
            with DbSession.use(readonly=False) as db:
                if failure == "role":
                    board[4].actions = ["read"]
                    db.update(board[4])
                else:
                    row = db.exec(SqlBuilder.select.table(AppConnection)).first()
                    if failure == "endpoint":
                        row.instance_url = "https://other.invalid"
                    else:
                        row.state = "disconnected"
                    db.update(row)

    if failure in {"role", "rotation", "endpoint", "disconnect"}:
        state["after"] = change
    else:
        state["failure"] = failure
    with pytest.raises((dk.DokployUnavailable, dk.DokployConflict)):
        dk.discover_resources(service, board[1], board[2].get_uid(), connection["connection_uid"])
    assert len(calls) == 2


def test_cross_project_environment_rejected(setup):
    service, board, _, calls, _ = setup
    connection = connect(setup)
    with pytest.raises(dk.DokployUnavailable):
        dk.discover_resources(
            service, board[1], board[2].get_uid(), connection["connection_uid"], "project-1", "foreign-env"
        )
    assert len(calls) == 2


@pytest.mark.parametrize("board", ["sqlite-http"], indirect=True)
def test_native_http_requires_current_board_authority(setup, monkeypatch):
    import importlib
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from langboard.middlewares.ApiAuthMiddleware import ApiAuthMiddleware
    from langboard.routes.board import BoardDokployAppApi as api
    from langboard_shared.core.db.DbEngine import DbEngine
    from langboard_shared.core.routing import AppRouter
    from langboard_shared.core.security import AuthSecurity

    service, board, reference, calls, _ = setup
    service.close = lambda: None
    monkeypatch.setattr(DbEngine, "get_readonly_engine", DbEngine.get_main_engine)
    monkeypatch.setattr(
        importlib.import_module("langboard.middlewares.ApiAuthMiddleware"), "DomainService", lambda: service
    )
    app = FastAPI()
    app.include_router(AppRouter.api)
    endpoints = {
        api.create_dokploy_connection,
        api.get_dokploy_connections,
        api.get_dokploy_resources,
        api.bind_dokploy_resource,
        api.get_dokploy_selected_resources,
        api.remove_dokploy_resource,
        api.disconnect_dokploy_connection,
        api.request_dokploy_secret_input,
        api.get_dokploy_secret_input,
        api.refresh_dokploy_deployments,
    }
    for route in app.routes:
        if getattr(route, "endpoint", None) in endpoints:
            for dependency in route.dependant.dependencies:
                if dependency.name == "service":
                    app.dependency_overrides[dependency.call] = lambda: service
    app.add_middleware(ApiAuthMiddleware, routes=AppRouter.api.routes)
    access, refresh = AuthSecurity.authenticate(board[1].id)
    headers = {"Authorization": "Bearer " + access}
    url = f"/board/{board[2].get_uid()}/settings/apps/dokploy/connections"
    form = {"instance_url": "https://deploy.example.invalid", "credential_reference": reference["uri"]}
    with TestClient(app) as client:
        assert client.post(url, json=form).status_code == 401
        client.cookies.set(Env.REFRESH_TOKEN_NAME, refresh)
        assert client.post(url, headers=headers, json={**form, "api_key": "must-not-be-accepted"}).status_code == 400
        response = client.post(url, headers=headers, json=form)
        assert response.status_code == 200 and response.headers["Cache-Control"] == "no-store"
        assert "fixture-api-key" not in response.text
        resource_url = url + "/" + response.json()["connection_uid"] + "/resources"
        result = client.get(
            resource_url, headers=headers, params={"external_project_id": "project-1", "environment_id": "env-1"}
        )
        assert result.status_code == 200 and len(result.json()["items"]) == 2 and "private" not in result.text
        input_url = url.removesuffix("/connections") + "/secret-input"
        secure = client.post(input_url, headers=headers)
        assert secure.status_code == 200 and secure.json()["state"] == "pending"
        input_uid = secure.json()["input_uid"]
        assert client.get(input_url + "/" + input_uid, headers=headers).json()["state"] == "pending"
        from langboard.secrets.SecretInput import complete_input, open_input

        _, proof = open_input(service, board[1], input_uid)
        completed = complete_input(service, board[1], input_uid, SecretStr("second-fixture-api-key"), proof)
        status = client.get(input_url + "/" + input_uid, headers=headers)
        assert status.json() == {"state": "completed", "secret_ref": completed["secret_ref"]}
        assert "second-fixture-api-key" not in status.text
        selected_url = resource_url.removesuffix("/resources") + "/selected"
        selection = {
            "resource_type": "application",
            "external_id": "app-1",
            "external_project_id": "project-1",
            "environment_id": "env-1",
            "expected_revision": response.json()["revision"],
        }
        chosen = client.post(selected_url, headers=headers, json=selection)
        assert chosen.status_code == 200
        signal_url = selected_url + "/" + chosen.json()["resource_uid"] + "/refresh"
        signal_form = {
            "expected_revision": response.json()["revision"],
            "expected_access_revision": chosen.json()["access_revision"],
        }
        assert client.post(signal_url, json=signal_form).status_code == 401
        assert (
            client.post(signal_url, headers=headers, json={**signal_form, "expected_access_revision": True}).status_code
            == 400
        )
        count = len(calls)
        assert client.post(signal_url, headers=headers, json=signal_form).status_code == 404
        assert len(calls) == count  # Resource selection never grants signal capabilities.
        access_url = resource_url.removesuffix("/resources") + "/enable-read"
        access = {
            "expected_revision": response.json()["revision"],
            "expected_binding_revision": client.get(selected_url, headers=headers).json()["binding"]["revision"],
        }
        assert client.post(access_url, json=access).status_code == 401
        assert client.post(access_url, headers=headers, json={**access, "enable_transitions": True}).status_code == 400
        assert (
            client.post(access_url, headers=headers, json={**access, "expected_binding_revision": "0" * 64}).status_code
            == 409
        )
        enabled = client.post(access_url, headers=headers, json=access)
        assert enabled.status_code == 200
        assert enabled.json()["granted_capabilities"] == ["resources.read", "signals.read", "deployments.read"]
        assert client.post(access_url, headers=headers, json=access).status_code == 409
        assert len(calls) == count  # Consent does not fetch/redeploy the provider.
        assert client.post(selected_url, headers=headers, json=selection).status_code == 409
        assert (
            client.get(selected_url, headers=headers).json()["items"][0]["resource_uid"]
            == chosen.json()["resource_uid"]
        )
        removal_url = selected_url + "/" + chosen.json()["resource_uid"] + "/remove"
        removal = {"expected_revision": chosen.json()["access_revision"]}
        assert client.post(removal_url, headers=headers, json=removal).status_code == 200
        assert client.post(removal_url, headers=headers, json=removal).status_code == 409
        disconnected_url = resource_url.removesuffix("/resources") + "/disconnect"
        assert client.post(disconnected_url, headers=headers, json={"expected_revision": "0" * 64}).status_code == 409
        with DbSession.use(readonly=False) as db:
            board[4].actions = ["read"]
            db.update(board[4])
        count = len(calls)
        assert client.post(selected_url, headers=headers, json=selection).status_code == 404
        assert client.post(removal_url, headers=headers, json=removal).status_code == 404
        assert (
            client.post(
                disconnected_url, headers=headers, json={"expected_revision": response.json()["revision"]}
            ).status_code
            == 404
        )
        assert client.get(url, headers=headers).status_code == 404
        assert client.get(resource_url, headers=headers).status_code == 404
        assert client.post(url, headers=headers, json=form).status_code == 404
        assert client.post(input_url, headers=headers).status_code == 404
        assert client.get(input_url + "/" + input_uid, headers=headers).status_code == 404
        assert len(calls) == count


def test_foreign_connection_owner_and_app_rejected_without_io(setup):
    service, board, _, calls, _ = setup
    connection = connect(setup)
    for field, value in (("owner_id", 2), ("app_key", "glitchtip")):
        with DbSession.use(readonly=False) as db:
            row = db.exec(SqlBuilder.select.table(AppConnection)).first()
            row.owner_id, row.app_key = board[1].id, "dokploy"
            setattr(row, field, value)
            db.update(row)
        count = len(calls)
        with pytest.raises(dk.DokployUnavailable):
            dk.discover_resources(service, board[1], board[2].get_uid(), connection["connection_uid"])
        assert len(calls) == count


@pytest.mark.parametrize(
    "kind,uid,parent,environment",
    [
        ("project", "project-1", None, None),
        ("environment", "env-1", "project-1", None),
        ("application", "app-1", "project-1", "env-1"),
        ("compose", "compose-1", "project-1", "env-1"),
    ],
)
def test_verified_selection_removal_and_disconnect_preserve_board(setup, kind, uid, parent, environment):
    service, board, reference, calls, _ = setup
    connection = connect(setup)
    args = service, board[1], board[2].get_uid(), connection["connection_uid"]
    before_selection = len(calls)
    selected = dk.bind_resource(*args, kind, uid, parent, environment, connection["revision"])
    assert [request.url.path for request in calls[before_selection:]] == {
        "project": ["/api/project.all"],
        "environment": ["/api/project.all", "/api/environment.byProjectId"],
        "application": ["/api/project.all", "/api/environment.byProjectId", "/api/environment.one"],
        "compose": ["/api/project.all", "/api/environment.byProjectId", "/api/environment.one"],
    }[kind]
    assert selected["selected"] and selected["access_state"] == "granted"
    assert selected["path"][-1]["id"] == uid and "private" not in json.dumps(selected)
    with DbSession.use(readonly=False) as db:
        binding = db.exec(SqlBuilder.select.table(BoardAppBinding)).first()
        assert binding.app_key == "dokploy" and binding.state == "disabled"
        assert not binding.granted_capabilities and not binding.stage_transitions_enabled
    assert dk.selected_resources(*args)["items"] == [selected]
    before = len(calls)
    removed = dk.remove_resource(*args, selected["resource_uid"], selected["access_revision"])
    assert not removed["selected"] and len(calls) == before
    with pytest.raises(dk.DokployConflict):
        dk.remove_resource(*args, selected["resource_uid"], selected["access_revision"])
    with pytest.raises(dk.DokployConflict):
        dk.bind_resource(*args, kind, uid, parent, environment, connection["revision"])
    again = dk.bind_resource(*args, kind, uid, parent, environment, connection["revision"], removed["access_revision"])
    assert again["resource_uid"] == selected["resource_uid"]
    with pytest.raises(dk.DokployConflict):
        dk.disconnect(*args, "0" * 64)
    dk.disconnect(*args, connection["revision"])
    with DbSession.use(readonly=False) as db:
        row = db.exec(SqlBuilder.select.table(AppResourceBinding)).first()
        assert row.is_selected and row.access_state == "revoked" and row.health == "unavailable"
        assert row.access_revision == again["access_revision"] + 1
        assert db.exec(SqlBuilder.select.table(BoardAppBinding)).first().state == "disabled"
    assert service.secret_reference.get_metadata(board[1], reference["uri"])["state"] == "active"
    with pytest.raises(dk.DokployUnavailable):
        dk.discover_resources(*args)


@pytest.mark.parametrize(
    "kind,uid,parent,environment",
    [
        ("application", "foreign-app", "project-1", "env-1"),
        ("compose", "app-1", "project-1", "env-1"),
        ("environment", "env-1", "foreign-project", None),
    ],
)
def test_invalid_hierarchy_never_creates_bindings(setup, kind, uid, parent, environment):
    service, board, _, _, _ = setup
    connection = connect(setup)
    with pytest.raises(dk.DokployUnavailable):
        dk.bind_resource(
            service,
            board[1],
            board[2].get_uid(),
            connection["connection_uid"],
            kind,
            uid,
            parent,
            environment,
            connection["revision"],
        )
    with DbSession.use(readonly=False) as db:
        assert not db.exec(SqlBuilder.select.table(AppResourceBinding)).all()
        assert not db.exec(SqlBuilder.select.table(BoardAppBinding)).all()


def test_bindings_are_independent_between_boards(setup):
    from langboard_shared.domain.models import ProjectAssignedUser, ProjectRole

    service, board, _, calls, _ = setup
    with DbSession.use(readonly=False) as db:
        db.insert(ProjectAssignedUser(project_id=11, user_id=board[1].id))
        db.insert(ProjectRole(project_id=11, user_id=board[1].id, actions=["read", "update"]))
    connection = connect(setup)
    from langboard_shared.helpers import InfraHelper

    first_args = service, board[1], board[2].get_uid(), connection["connection_uid"]
    second_args = service, board[1], InfraHelper.convert_uid(11), connection["connection_uid"]
    first = dk.bind_resource(*first_args, "project", "project-1", None, None, connection["revision"])
    second = dk.bind_resource(*second_args, "project", "project-1", None, None, connection["revision"])
    assert first["resource_uid"] != second["resource_uid"]
    with pytest.raises(dk.DokployUnavailable):
        dk.remove_resource(*second_args, first["resource_uid"], first["access_revision"])
    dk.remove_resource(*first_args, first["resource_uid"], first["access_revision"])
    assert dk.selected_resources(*second_args)["items"] == [second]
    dk.disconnect(*first_args, connection["revision"])
    with DbSession.use(readonly=False) as db:
        rows = db.exec(SqlBuilder.select.table(AppResourceBinding)).all()
        assert len(rows) == 2 and all(row.access_state == "revoked" for row in rows)
        assert sorted(row.is_selected for row in rows) == [False, True]
        assert len(db.exec(SqlBuilder.select.table(BoardAppBinding)).all()) == 2


@pytest.mark.parametrize("failure", ["role", "rotation", "disconnect"])
def test_inflight_authority_change_rolls_back_binding(setup, failure):
    service, board, reference, _, state = setup
    connection = connect(setup)

    def change():
        if failure == "rotation":
            service.secret_reference.rotate(board[1], reference["uri"], SecretStr("new-key"), reference["revision"])
        else:
            with DbSession.use(readonly=False) as db:
                if failure == "role":
                    board[4].actions = ["read"]
                    db.update(board[4])
                else:
                    row = db.exec(SqlBuilder.select.table(AppConnection)).first()
                    row.state = "disconnected"
                    db.update(row)

    state["after"] = change
    with pytest.raises((dk.DokployUnavailable, dk.DokployConflict)):
        dk.bind_resource(
            service,
            board[1],
            board[2].get_uid(),
            connection["connection_uid"],
            "project",
            "project-1",
            None,
            None,
            connection["revision"],
        )
    with DbSession.use(readonly=False) as db:
        assert not db.exec(SqlBuilder.select.table(AppResourceBinding)).all()
        assert not db.exec(SqlBuilder.select.table(BoardAppBinding)).all()


def test_binding_audit_is_atomic_with_connection_and_resource(setup, monkeypatch):
    service, board, reference, *_ = setup
    connection = connect(setup)
    events = service.secret_reference.list_audit(board[1], reference["uri"])["items"]
    assert events[0]["action"] == "bound" and events[0]["reason_code"] == "reference_bound"
    args = (service, board[1], board[2].get_uid(), connection["connection_uid"])

    def bind():
        return dk.bind_resource(*args, "application", "app-1", "project-1", "env-1", connection["revision"])

    original = service.secret_reference.audit_binding

    def fail_after_receipt(*args, **kwargs):
        original(*args, **kwargs)
        raise RuntimeError("Destination audit failure")

    monkeypatch.setattr(service.secret_reference, "audit_binding", fail_after_receipt)
    with pytest.raises(RuntimeError):
        bind()
    with DbSession.use(readonly=False) as db:
        assert not db.exec(SqlBuilder.select.table(AppResourceBinding)).all()
    assert (
        sum(x["action"] == "bound" for x in service.secret_reference.list_audit(board[1], reference["uri"])["items"])
        == 1
    )
    with pytest.raises(RuntimeError):
        connect(setup)
    with DbSession.use(readonly=False) as db:
        assert len(db.exec(SqlBuilder.select.table(AppConnection)).all()) == 1
    monkeypatch.setattr(service.secret_reference, "audit_binding", original)
    bind()
    assert service.secret_reference.list_audit(board[1], reference["uri"])["items"][0]["action"] == "bound"


@pytest.mark.parametrize("state", ["connected", "pending", "revoked", "disconnected"])
def test_policy_disabled_connection_can_only_remove_authority(setup, state):
    from langboard_shared.domain.models import AppGovernancePolicy

    service, board, _, calls, _ = setup
    connection = connect(setup)
    args = service, board[1], board[2].get_uid(), connection["connection_uid"]
    selected = dk.bind_resource(*args, "application", "app-1", "project-1", "env-1", connection["revision"])
    with DbSession.use(readonly=False) as db:
        db.insert(AppGovernancePolicy(scope_key="global", mode="disabled"))
        stored = db.exec(SqlBuilder.select.table(AppConnection)).first()
        stored.state = state
        if state == "revoked":
            stored.credential_reference = None
        db.update(stored)
        revision = dk._revision(stored)
        board[4].actions = ["read"]
        db.update(board[4])
    before = len(calls)
    with pytest.raises(dk.DokployUnavailable):
        dk.disconnect(*args, revision)
    with pytest.raises(dk.DokployUnavailable):
        dk.list_connections(*args[:3])
    with pytest.raises(dk.DokployUnavailable):
        dk.selected_resources(*args)
    with DbSession.use(readonly=False) as db:
        board[4].actions = ["read", "update"]
        db.update(board[4])
    with pytest.raises(dk.DokployUnavailable):
        dk.discover_resources(*args)
    listed = dk.list_connections(*args[:3])["items"]
    assert listed[0]["state"] == state and listed[0]["revision"] == revision
    resources = dk.selected_resources(*args)["items"]
    assert resources[0]["resource_uid"] == selected["resource_uid"]
    assert resources[0]["access_revision"] == selected["access_revision"]
    with pytest.raises(dk.DokployConflict):
        dk.disconnect(*args, "0" * 64)
    removed = dk.remove_resource(*args, selected["resource_uid"], selected["access_revision"])
    assert removed["selected"] is False
    result = dk.disconnect(*args, revision)
    assert result["state"] == "disconnected"
    assert dk.list_connections(*args[:3])["items"][0]["revision"] == result["revision"]
    assert len(calls) == before
    with DbSession.use(readonly=False) as db:
        resource = db.exec(SqlBuilder.select.table(AppResourceBinding)).first()
        assert resource.access_state == "revoked" and resource.health == "unavailable"
        assert resource.is_selected is False
