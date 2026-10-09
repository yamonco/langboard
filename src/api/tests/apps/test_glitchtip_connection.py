# ruff: noqa: F811
"""Real host authority/storage with bounded official GlitchTip metadata I/O."""

import importlib
import json
from types import SimpleNamespace
import httpx
import pytest
from langboard.apps import GlitchTipConnection as gt
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
    service = SimpleNamespace(workflow_stage=board[0], secret_reference=secret_service, close=lambda: None)
    reference = secret_service.create(board[1], "personal", "me", "glitchtip/admin", SecretStr("fixture-admin-token"))
    original_env = Env.get_from_env
    monkeypatch.setattr(
        Env,
        "get_from_env",
        lambda key, default=None: "https://errors.example.invalid"
        if key == "APP_CONNECTION_ALLOWED_BASE_URLS"
        else original_env(key, default),
    )
    calls = []
    state = {"status": 200, "after": None, "oversize": False}

    def external(request):
        calls.append(request)
        assert request.url.host == "errors.example.invalid"
        assert request.headers["Authorization"] == "Bearer fixture-admin-token"
        assert request.method == "GET"
        if state["after"]:
            state["after"]()
        if state.get("network_error"):
            raise httpx.ConnectError("private provider failure", request=request)
        if state["oversize"]:
            return httpx.Response(200, content=b" " * 262145)
        if state["status"] != 200:
            return httpx.Response(state["status"], headers={"Location": "https://attacker.invalid/"})
        org = {"id": "1", "slug": "test-org", "name": "Organization"}
        project = {
            "id": "2",
            "slug": "test-project",
            "name": "Project",
            "hasAccess": True,
            "organization": org,
            "dsn": "never-project-this",
        }
        if request.url.path == "/api/0/organizations/":
            return httpx.Response(200, json=[org])
        if request.url.path == "/api/0/organizations/test-org/projects/":
            return httpx.Response(
                200,
                json=[project],
                headers={"Link": '<https://attacker.invalid/?cursor=123:0:0>; rel="next"; results="true"'},
            )
        assert request.url.path == "/api/0/projects/test-org/test-project/"
        return httpx.Response(200, json=project)

    original_client = httpx.Client
    monkeypatch.setattr(
        transport.httpx, "Client", lambda **kwargs: original_client(transport=httpx.MockTransport(external), **kwargs)
    )
    return service, board, reference, calls, state


def connect(setup):
    service, board, reference, *_ = setup
    return gt.register_connection(
        service, board[1], board[2].get_uid(), "https://errors.example.invalid/", reference["uri"]
    )


def test_register_discover_bind_disconnect_preserves_workflow(setup):
    service, board, reference, calls, _ = setup
    connection = connect(setup)
    assert connection["official_mcp_url"] == "https://errors.example.invalid/mcp"
    assert "fixture-admin-token" not in json.dumps(connection) and "credential_reference" not in connection
    uid, project_uid = connection["connection_uid"], board[2].get_uid()
    assert gt.list_connections(service, board[1], project_uid)["items"] == [connection]
    resources = gt.discover_resources(service, board[1], project_uid, uid, "test-org")
    assert resources["items"] == [{"id": "2", "slug": "test-project", "name": "Project"}]
    assert resources["next_cursor"] == "123:0:0"
    gt.discover_resources(service, board[1], project_uid, uid, "test-org", resources["next_cursor"])
    assert calls[-1].url.host == "errors.example.invalid" and calls[-1].url.params["cursor"] == "123:0:0"
    result = gt.bind_project(service, board[1], project_uid, uid, "test-org", "test-project", connection["revision"])
    assert result["access_state"] == "granted"
    with DbSession.use(readonly=False) as db:
        binding = db.exec(SqlBuilder.select.table(BoardAppBinding)).first()
        row = db.exec(SqlBuilder.select.table(AppResourceBinding)).first()
        assert (
            binding.state == "disabled" and not binding.stage_transitions_enabled and not binding.granted_capabilities
        )
        assert row.resource_path[-1]["slug"] == "test-project" and "never-project-this" not in json.dumps(
            row.model_dump(), default=str
        )
    gt.disconnect(service, board[1], project_uid, uid, connection["revision"])
    with DbSession.use(readonly=False) as db:
        row = db.exec(SqlBuilder.select.table(AppResourceBinding)).first()
        assert row.is_selected and row.access_state == "revoked" and row.health == "unavailable"
        assert db.exec(SqlBuilder.select.table(BoardAppBinding)).first().state == "disabled"
    with pytest.raises(gt.GlitchTipUnavailable):
        gt.discover_resources(service, board[1], project_uid, uid)
    assert service.secret_reference.get_metadata(board[1], reference["uri"])["state"] == "active"


@pytest.mark.parametrize(
    "bad",
    [
        "http://errors.example.invalid",
        "https://other.invalid",
        "https://user@errors.example.invalid",
        "https://errors.example.invalid?token=private",
        "https://errors.example.invalid/../admin",
    ],
)
def test_unapproved_or_credential_urls_rejected_without_io(setup, bad):
    service, board, reference, calls, _ = setup
    with pytest.raises(ValueError):
        gt.register_connection(service, board[1], board[2].get_uid(), bad, reference["uri"])
    assert not calls


def test_dsn_never_used_as_admin_credential(setup):
    service, board, _, calls, _ = setup
    reference = service.secret_reference.create(
        board[1], "personal", "me", "glitchtip/dsn", SecretStr("https://public-key@errors.example.invalid/42")
    )
    with pytest.raises(gt.GlitchTipUnavailable):
        gt.register_connection(
            service, board[1], board[2].get_uid(), "https://errors.example.invalid", reference["uri"]
        )
    assert not calls


def test_owner_scope_and_bounded_connection_pages(setup):
    service, board, reference, calls, _ = setup
    with DbSession.use(readonly=False) as db:
        for i in range(27):
            db.insert(
                AppConnection(
                    app_key="glitchtip",
                    owner_id=board[1].id,
                    instance_url="https://errors.example.invalid",
                    credential_reference=reference["uri"],
                    state="connected",
                )
            )
        foreign = AppConnection(
            app_key="glitchtip",
            owner_id=2,
            instance_url="https://errors.example.invalid",
            credential_reference=reference["uri"],
            state="connected",
        )
        db.insert(foreign)
    first = gt.list_connections(service, board[1], board[2].get_uid())
    second = gt.list_connections(service, board[1], board[2].get_uid(), first["next_cursor"])
    assert len(first["items"]) == 25 and len(second["items"]) == 2 and second["next_cursor"] is None
    assert {item["connection_uid"] for item in first["items"]}.isdisjoint(
        item["connection_uid"] for item in second["items"]
    )
    with pytest.raises(gt.GlitchTipUnavailable):
        gt.discover_resources(service, board[1], board[2].get_uid(), foreign.get_uid())
    assert not calls


def test_selection_removal_revision_and_board_scope(setup):
    service, board, _, calls, _ = setup
    connection = connect(setup)
    args = (service, board[1], board[2].get_uid(), connection["connection_uid"])
    selected = gt.bind_project(*args, "test-org", "test-project", connection["revision"])
    before_calls = len(calls)
    removed = gt.remove_project(*args, selected["resource_uid"], selected["access_revision"])
    assert not removed["selected"] and len(calls) == before_calls
    page = gt.selected_projects(*args)
    assert page["items"][0]["selected"] is False
    with pytest.raises(gt.GlitchTipConflict):
        gt.remove_project(*args, selected["resource_uid"], selected["access_revision"])
    with pytest.raises(gt.GlitchTipConflict):
        gt.bind_project(*args, "test-org", "test-project", connection["revision"])
    again = gt.bind_project(*args, "test-org", "test-project", connection["revision"], removed["access_revision"])
    assert again["resource_uid"] == selected["resource_uid"]
    assert gt.selected_projects(*args)["items"][0]["selected"] is True
    with pytest.raises(gt.GlitchTipUnavailable):
        gt.remove_project(
            service, board[1], "b", connection["connection_uid"], selected["resource_uid"], again["access_revision"]
        )


@pytest.mark.parametrize("failure", ["role", "rotation", "endpoint", "disconnect", "oversize", "redirect"])
def test_inflight_changes_never_bind_or_return_stale_metadata(setup, failure):
    service, board, reference, calls, state = setup
    connection = connect(setup)
    uid = connection["connection_uid"]

    def change():
        if failure == "rotation":
            service.secret_reference.rotate(board[1], reference["uri"], SecretStr("new-token"), reference["revision"])
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
    elif failure == "oversize":
        state["oversize"] = True
    else:
        state["status"] = 302
    with pytest.raises((gt.GlitchTipUnavailable, gt.GlitchTipConflict)):
        gt.bind_project(service, board[1], board[2].get_uid(), uid, "test-org", "test-project", connection["revision"])
    with DbSession.use(readonly=False) as db:
        assert not db.exec(SqlBuilder.select.table(AppResourceBinding)).all()
    assert len(calls) == 2


@pytest.mark.parametrize("board", ["sqlite-http"], indirect=True)
def test_authenticated_native_http_metadata_only(setup, monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from langboard.middlewares.ApiAuthMiddleware import ApiAuthMiddleware
    from langboard.routes.board import BoardGlitchTipAppApi as api
    from langboard_shared.core.db.DbEngine import DbEngine
    from langboard_shared.core.routing import AppRouter
    from langboard_shared.core.security import AuthSecurity

    service, board, reference, calls, state = setup
    monkeypatch.setattr(DbEngine, "get_readonly_engine", DbEngine.get_main_engine)
    monkeypatch.setattr(
        importlib.import_module("langboard.middlewares.ApiAuthMiddleware"), "DomainService", lambda: service
    )
    app = FastAPI()
    app.include_router(AppRouter.api)
    endpoints = {
        api.create_glitchtip_connection,
        api.get_glitchtip_connections,
        api.get_glitchtip_resources,
        api.bind_glitchtip_project,
        api.disconnect_glitchtip_connection,
        api.get_glitchtip_selected_projects,
        api.remove_glitchtip_project,
        api.request_glitchtip_secret_input,
        api.get_glitchtip_secret_input,
    }
    for route in app.routes:
        if getattr(route, "endpoint", None) in endpoints:
            for dependency in route.dependant.dependencies:
                if dependency.name == "service":
                    app.dependency_overrides[dependency.call] = lambda: service
    app.add_middleware(ApiAuthMiddleware, routes=AppRouter.api.routes)
    access, refresh = AuthSecurity.authenticate(board[1].id)
    headers = {"Authorization": "Bearer " + access}
    url = f"/board/{board[2].get_uid()}/settings/apps/glitchtip/connections"
    form = {"instance_url": "https://errors.example.invalid", "credential_reference": reference["uri"]}
    with TestClient(app) as client:
        assert client.post(url, json=form).status_code == 401
        client.cookies.set(Env.REFRESH_TOKEN_NAME, refresh)
        assert client.post(url, headers=headers, json={**form, "dsn": "unexpected"}).status_code == 400
        response = client.post(url, headers=headers, json=form)
        assert response.status_code == 200 and response.headers["Cache-Control"] == "no-store"
        assert "fixture-admin-token" not in response.text
        connection = response.json()
        resource_url = url + "/" + connection["connection_uid"]
        assert client.get(resource_url + "/resources?organization=test-org", headers=headers).status_code == 200
        selected = client.post(
            resource_url + "/projects",
            headers=headers,
            json={
                "organization": "test-org",
                "project_slug": "test-project",
                "expected_revision": connection["revision"],
            },
        )
        assert selected.status_code == 200
        assert client.get(resource_url + "/projects", headers=headers).json()["items"][0]["selected"]
        removal = resource_url + "/projects/" + selected.json()["resource_uid"] + "/remove"
        payload = {"expected_revision": selected.json()["access_revision"]}
        assert client.post(removal, headers=headers, json=payload).status_code == 200
        assert client.post(removal, headers=headers, json=payload).status_code == 409
        input_url = url.removesuffix("/connections") + "/secret-input"
        secure = client.post(input_url, headers=headers)
        assert secure.status_code == 200 and secure.json()["state"] == "pending"
        uid = secure.json()["input_uid"]
        assert client.get(input_url + "/" + uid, headers=headers).json()["state"] == "pending"
        from langboard.secrets.SecretInput import complete_input, open_input

        _, proof = open_input(service, board[1], uid)
        completed = complete_input(service, board[1], uid, SecretStr("second-fixture-api-token"), proof)
        status = client.get(input_url + "/" + uid, headers=headers)
        assert status.json() == {"state": "completed", "secret_ref": completed["secret_ref"]}
        assert "second-fixture-api-token" not in status.text
        with DbSession.use(readonly=False) as db:
            connection_count = len(db.exec(SqlBuilder.select.table(AppConnection)).all())
        state["network_error"] = True
        try:
            failed = client.post(url, headers=headers, json=form)
            assert failed.status_code == 503
            assert "private provider failure" not in failed.text and "fixture-admin-token" not in failed.text
        finally:
            state["network_error"] = False
        with DbSession.use(readonly=False) as db:
            assert len(db.exec(SqlBuilder.select.table(AppConnection)).all()) == connection_count
        with DbSession.use(readonly=False) as db:
            board[4].actions = ["read"]
            db.update(board[4])
        count = len(calls)
        assert client.get(url, headers=headers).status_code == 404
        assert client.get(resource_url + "/resources", headers=headers).status_code == 404
        assert client.post(input_url, headers=headers).status_code == 404
        assert client.get(input_url + "/" + uid, headers=headers).status_code == 404
        assert len(calls) == count


def test_binding_audit_is_atomic_with_connection_and_resource(setup, monkeypatch):
    service, board, reference, *_ = setup
    connection = connect(setup)
    events = service.secret_reference.list_audit(board[1], reference["uri"])["items"]
    assert events[0]["action"] == "bound" and events[0]["reason_code"] == "reference_bound"
    args = (service, board[1], board[2].get_uid(), connection["connection_uid"])

    def bind():
        return gt.bind_project(*args, "test-org", "test-project", connection["revision"])

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
