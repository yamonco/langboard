# ruff: noqa: F811
"""Native SQLite authority and HTTP proofs for bounded status observations."""

import importlib
import json
import pytest
from langboard.apps import GlitchTipConnection as gt
from langboard.apps import GlitchTipSignal as signal
from langboard_shared.core.db import DbSession, SqlBuilder
from langboard_shared.core.db.DbEngine import DbEngine
from langboard_shared.domain.models import (
    AppConnection,
    AppResourceBinding,
    AppSignal,
    BoardAppBinding,
    SecretReference,
)
from langboard_shared.domain.services.factory.SecretReferenceService_test import secrets  # noqa: F401
from langboard_shared.domain.services.factory.WorkflowStageService_app_test import board  # noqa: F401
from langboard_shared.publishers import CardPublisher
from test_glitchtip_connection import connect, setup  # noqa: F401


def test_read_revocation_preserves_other_grants_without_provider_io(selected):
    setup, connection, *_ = selected
    service, board, *_ = setup
    calls = setup[3]
    with DbSession.use(readonly=False) as db:
        binding = db.exec(SqlBuilder.select.table(BoardAppBinding)).first()
        binding.granted_capabilities = [*binding.granted_capabilities, "panels.render", "workflow.transition"]
        binding.stage_transitions_enabled = True
        db.update(binding)
        revision = binding.edit_revision()
    count = len(calls)
    with pytest.raises(gt.GlitchTipConflict):
        gt.disable_read_access(service, board[1], board[2].get_uid(), connection["connection_uid"], connection["revision"], "0" * 64)
    result = gt.disable_read_access(service, board[1], board[2].get_uid(), connection["connection_uid"], connection["revision"], revision)
    assert result["granted_capabilities"] == ["panels.render", "workflow.transition"] and result["state"] == "enabled"
    assert len(calls) == count
    with DbSession.use(readonly=False) as db:
        current = db.exec(SqlBuilder.select.table(BoardAppBinding)).first()
        assert current.stage_transitions_enabled
    # Current read gates reject the removed grant before making any provider request.
    with pytest.raises(gt.GlitchTipUnavailable):
        refresh(selected)
    assert len(calls) == count


def test_read_consent_preserves_independent_existing_grants(selected):
    setup, connection, *_ = selected
    service, board, *_ = setup
    with DbSession.use(readonly=False) as db:
        binding = db.exec(SqlBuilder.select.table(BoardAppBinding)).first()
        binding.granted_capabilities = ["panels.render", "workflow.transition"]
        binding.stage_transitions_enabled = True
        db.update(binding)
        revision = binding.edit_revision()
    result = gt.enable_read_access(
        service, board[1], board[2].get_uid(), connection["connection_uid"], connection["revision"], revision
    )
    expected = ["panels.render", "workflow.transition", "resources.read", "signals.read"]
    assert result["granted_capabilities"] == expected
    repeated = gt.enable_read_access(
        service, board[1], board[2].get_uid(), connection["connection_uid"], connection["revision"], result["revision"]
    )
    assert repeated["granted_capabilities"] == expected
    with DbSession.use(readonly=False) as db:
        current = db.exec(SqlBuilder.select.table(BoardAppBinding)).first()
        assert current.granted_capabilities == expected and current.stage_transitions_enabled

@pytest.fixture
def selected(setup, monkeypatch):
    service, board, _, _, state = setup
    conn = connect(setup)
    chosen = gt.bind_project(
        service, board[1], board[2].get_uid(), conn["connection_uid"], "test-org", "test-project", conn["revision"]
    )
    AppSignal.__table__.create(DbEngine.get_main_engine(), checkfirst=True)
    with DbSession.use(readonly=False) as db:
        binding = db.exec(SqlBuilder.select.table(BoardAppBinding)).first()
        revision = binding.edit_revision()
    enabled = gt.enable_read_access(
        service, board[1], board[2].get_uid(), conn["connection_uid"], conn["revision"], revision
    )
    assert enabled["granted_capabilities"] == ["resources.read", "signals.read"]
    state["rows"] = [
        {
            "id": "10",
            "project": {"id": "2", "slug": "test-project"},
            "status": "unresolved",
            "firstSeen": "2026-10-08T00:00:00Z",
            "lastSeen": "2026-10-08T00:01:00Z",
            "title": "private title",
            "rawstack": "private stack",
            "events": ["secret"],
        }
    ]
    original = gt._get
    state["original_get"] = original
    state["issue_calls"] = 0

    def get(base, token, path, params=None):
        if path.endswith("/issues/"):
            assert params["limit"] == 25 and params["sort"] == "-last_seen"
            state["issue_calls"] += 1
            if state.get("after_issues"):
                state["after_issues"]()
            return state["rows"], state.get("next_cursor")
        return original(base, token, path, params)

    monkeypatch.setattr(gt, "_get", get)
    events = []
    monkeypatch.setattr(CardPublisher, "app_signal_changed", lambda uid: events.append(uid))
    return setup, conn, chosen, events


def refresh(selected, **kwargs):
    setup, conn, chosen, _ = selected
    service, board, *_ = setup
    return signal.refresh_issues(
        service,
        board[1],
        board[2].get_uid(),
        conn["connection_uid"],
        chosen["resource_uid"],
        conn["revision"],
        chosen["access_revision"],
        **kwargs,
    )


def stored():
    with DbSession.use(readonly=False) as db:
        return db.exec(SqlBuilder.select.table(AppSignal).order_by(AppSignal.id)).all()


def test_observations_idempotent_cycles_and_empty_page(selected):
    first = refresh(selected)
    assert first["accepted_count"] == 1 and first["semantics"] == "status_observation"
    assert first["items"][0]["event_type"] == "issue.status_observed"
    assert first["items"][0]["occurred_at"] != selected[0][4]["rows"][0]["lastSeen"]
    assert refresh(selected)["accepted_count"] == 0
    row = selected[0][4]["rows"][0]
    row["status"] = "resolved"
    assert refresh(selected)["accepted_count"] == 1
    row["status"] = "unresolved"
    assert refresh(selected)["accepted_count"] == 1
    assert refresh(selected)["accepted_count"] == 0
    records = stored()
    assert [r.outcome for r in records] == ["unresolved", "resolved", "unresolved"]
    assert len({r.event_id for r in records}) == 3
    assert all(r.commit_sha == "" for r in records)
    assert "private" not in json.dumps([r.model_dump() for r in records], default=str)
    assert len(selected[3]) == 3
    selected[0][4]["rows"] = []
    assert refresh(selected)["accepted_count"] == 0 and len(stored()) == 3


@pytest.mark.parametrize(
    "mutation",
    [
        {"id": True},
        {"id": "-1"},
        {"status": []},
        {"status": "reopened"},
        {"project": {"id": "3", "slug": "test-project"}},
        {"project": {"id": "2", "slug": "foreign"}},
        {"firstSeen": "2026-10-08T00:03:00Z"},
        {"lastSeen": "2026-10-08T00:01:00"},
        {"lastSeen": "2999-10-08T00:01:00Z"},
        {"firstSeen": None},
    ],
)
def test_invalid_batch_is_atomic(selected, mutation):
    selected[0][4]["rows"].append({**selected[0][4]["rows"][0], **mutation})
    with pytest.raises(gt.GlitchTipUnavailable):
        refresh(selected)
    assert stored() == [] and not selected[3]


def test_limits_cursor_and_duplicates(selected):
    state = selected[0][4]
    state["rows"] *= 2
    state["next_cursor"] = "123:0:0"
    assert refresh(selected, cursor="123:0:0")["accepted_count"] == 1
    assert refresh(selected)["next_cursor"] == "123:0:0"
    state["rows"] *= 13
    with pytest.raises(gt.GlitchTipUnavailable):
        refresh(selected)
    before = state["issue_calls"]
    with pytest.raises(ValueError):
        refresh(selected, cursor="https://attacker.invalid")
    assert state["issue_calls"] == before


def mutate(selected, failure):
    setup, _, _, _ = selected
    with DbSession.use(readonly=False) as db:
        binding = db.exec(SqlBuilder.select.table(BoardAppBinding)).first()
        resource = db.exec(SqlBuilder.select.table(AppResourceBinding)).first()
        conn = db.exec(SqlBuilder.select.table(AppConnection)).first()
        secret = db.exec(SqlBuilder.select.table(SecretReference)).first()
        if failure == "role":
            setup[1][4].actions = ["read"]
            db.update(setup[1][4])
        elif failure == "secret":
            secret.state = "revoked"
            db.update(secret)
        elif failure == "owner":
            conn.owner_id = 2
            db.update(conn)
        elif failure == "connection":
            conn.state = "disconnected"
            db.update(conn)
        elif failure == "endpoint":
            conn.instance_url = "https://attacker.invalid"
            db.update(conn)
        elif failure == "capability":
            binding.granted_capabilities = []
            db.update(binding)
        elif failure == "binding":
            binding.state = "disabled"
            db.update(binding)
        elif failure == "hierarchy":
            resource.resource_path = []
            db.update(resource)
        elif failure == "selected":
            resource.is_selected = False
            db.update(resource)
        elif failure == "resource":
            resource.access_state = "revoked"
            db.update(resource)
        else:
            resource.access_revision += 1
            db.update(resource)


@pytest.mark.parametrize(
    "failure",
    [
        "role",
        "secret",
        "owner",
        "connection",
        "endpoint",
        "capability",
        "binding",
        "hierarchy",
        "selected",
        "resource",
        "revision",
    ],
)
@pytest.mark.parametrize("inflight", [False, True])
def test_current_and_inflight_revocations(selected, failure, inflight):
    from langboard_shared.domain.services.factory.SecretReferenceService import SecretReferenceUnavailable

    if inflight:
        selected[0][4]["after_issues"] = lambda: mutate(selected, failure)
    else:
        mutate(selected, failure)
    before = selected[0][4]["issue_calls"]
    with pytest.raises((gt.GlitchTipUnavailable, gt.GlitchTipConflict, SecretReferenceUnavailable, ValueError)):
        refresh(selected)
    assert not stored() and not selected[3]
    if not inflight:
        assert selected[0][4]["issue_calls"] == before


def test_stale_inflight_refresh_cannot_overwrite_newer_observation(selected):
    state = selected[0][4]

    def newer():
        state["after_issues"] = None
        state["rows"][0]["status"] = "resolved"
        assert refresh(selected)["accepted_count"] == 1
        state["rows"][0]["status"] = "unresolved"

    state["after_issues"] = newer
    with pytest.raises(gt.GlitchTipConflict):
        refresh(selected)
    assert [r.outcome for r in stored()] == ["resolved"]


@pytest.mark.parametrize(
    "failure", ["binding_revision", "connection_revision", "selected", "role", "secret", "owner", "connection"]
)
def test_consent_requires_current_authority(selected, failure):
    from langboard_shared.domain.services.factory.SecretReferenceService import SecretReferenceUnavailable

    setup, conn, _, _ = selected
    with DbSession.use(readonly=False) as db:
        binding = db.exec(SqlBuilder.select.table(BoardAppBinding)).first()
        binding.state = "disabled"
        binding.granted_capabilities = []
        db.update(binding)
        revision = binding.edit_revision()
    if failure not in {"binding_revision", "connection_revision"}:
        mutate(selected, failure)
    with pytest.raises((gt.GlitchTipUnavailable, gt.GlitchTipConflict, SecretReferenceUnavailable)):
        gt.enable_read_access(
            setup[0],
            setup[1][1],
            setup[1][2].get_uid(),
            conn["connection_uid"],
            "0" * 64 if failure == "connection_revision" else conn["revision"],
            "0" * 64 if failure == "binding_revision" else revision,
        )
    with DbSession.use(readonly=False) as db:
        binding = db.exec(SqlBuilder.select.table(BoardAppBinding)).first()
        assert binding.state == "disabled" and not binding.granted_capabilities


@pytest.mark.parametrize("board", ["sqlite-http"], indirect=True)
def test_authenticated_http(selected, monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from langboard.middlewares.ApiAuthMiddleware import ApiAuthMiddleware
    from langboard.routes.board import BoardGlitchTipAppApi as api
    from langboard_shared.core.routing import AppRouter
    from langboard_shared.core.security import AuthSecurity
    from langboard_shared.Env import Env

    setup, conn, chosen, _ = selected
    service, board, *_ = setup
    monkeypatch.setattr(DbEngine, "get_readonly_engine", DbEngine.get_main_engine)
    monkeypatch.setattr(
        importlib.import_module("langboard.middlewares.ApiAuthMiddleware"), "DomainService", lambda: service
    )
    app = FastAPI()
    app.include_router(AppRouter.api)
    for route in app.routes:
        if getattr(route, "endpoint", None) in {api.enable_glitchtip_read_access, api.disable_glitchtip_read_access, api.refresh_glitchtip_issues}:
            for dep in route.dependant.dependencies:
                if dep.name == "service":
                    app.dependency_overrides[dep.call] = lambda: service
    app.add_middleware(ApiAuthMiddleware, routes=AppRouter.api.routes)
    access, cookie = AuthSecurity.authenticate(board[1].id)
    headers = {"Authorization": "Bearer " + access}
    base = f"/board/{board[2].get_uid()}/settings/apps/glitchtip/connections/{conn['connection_uid']}"
    url = base + f"/projects/{chosen['resource_uid']}/issues/refresh"
    form = {"expected_connection_revision": conn["revision"], "expected_access_revision": chosen["access_revision"]}
    with TestClient(app) as client:
        assert client.post(url, json=form).status_code == 401
        client.cookies.set(Env.REFRESH_TOKEN_NAME, cookie)
        assert client.post(url, headers=headers, json={**form, "approval": True}).status_code == 400
        assert client.post(url, headers=headers, json={**form, "expected_access_revision": True}).status_code == 400
        assert client.post(url, headers=headers, json={**form, "cursor": "https://attacker.invalid"}).status_code == 400
        response = client.post(url, headers=headers, json=form)
        assert response.status_code == 200 and response.headers["Cache-Control"] == "no-store"
        assert response.json()["accepted_count"] == 1 and "private" not in response.text
        assert (
            client.post(url, headers=headers, json={**form, "expected_connection_revision": "0" * 64}).status_code
            == 409
        )
        with DbSession.use(readonly=False) as db:
            binding = db.exec(SqlBuilder.select.table(BoardAppBinding)).first()
            binding.state = "disabled"
            binding.granted_capabilities = []
            db.update(binding)
            revision = binding.edit_revision()
        consent = {"expected_connection_revision": conn["revision"], "expected_binding_revision": revision}
        enabled = client.post(base + "/read-access", headers=headers, json=consent)
        assert enabled.status_code == 200
        assert client.post(base + "/read-access", headers=headers, json=consent).status_code == 409
        revoke = {**consent, "expected_binding_revision": enabled.json()["revision"]}
        assert client.post(base + "/disable-read", json=revoke).status_code == 401
        assert client.post(base + "/disable-read", headers=headers, json={**revoke, "approval": True}).status_code == 400
        assert client.post(base + "/disable-read", headers=headers, json=revoke).status_code == 200
        assert client.post(url, headers=headers, json=form).status_code == 404
        mutate(selected, "role")
        assert client.post(url, headers=headers, json=form).status_code == 404


@pytest.mark.parametrize("failure", [None, "redirect", "oversize", "bad_cursor", "foreign_project"])
def test_approved_issue_transport(selected, monkeypatch, failure):
    import httpx
    from langboard.apps import MetadataTransport as transport

    state = selected[0][4]
    monkeypatch.setattr(gt, "_get", state["original_get"])
    from httpx._client import Client

    native_client = Client
    calls = []

    def external(request):
        calls.append(request)
        assert request.method == "GET" and request.url.host == "errors.example.invalid"
        assert request.headers["Authorization"] == "Bearer fixture-admin-token"
        if request.url.path.endswith("/issues/"):
            assert dict(request.url.params) == {"limit": "25", "sort": "-last_seen", "cursor": "123:0:0"}
            if failure == "redirect":
                return httpx.Response(302, headers={"Location": "https://attacker.invalid"})
            if failure == "oversize":
                return httpx.Response(200, content=b" " * 262145)
            cursor = "invalid%2Fcursor" if failure == "bad_cursor" else "456:0:0"
            return httpx.Response(
                200,
                json=state["rows"],
                headers={
                    "Link": f'<https://attacker.invalid/?cursor={cursor}>; rel="next"; results="true"',
                },
            )
        return httpx.Response(
            200,
            json={
                "id": "3" if failure == "foreign_project" else "2",
                "slug": "test-project",
                "hasAccess": True,
                "organization": {"slug": "test-org"},
            },
        )

    monkeypatch.setattr(
        transport.httpx,
        "Client",
        lambda **kwargs: native_client(
            transport=httpx.MockTransport(external),
            **kwargs,
        ),
    )
    if failure:
        with pytest.raises(gt.GlitchTipUnavailable):
            refresh(selected, cursor="123:0:0")
        assert not stored() and not selected[3]
        assert len(calls) == (1 if failure == "foreign_project" else 2)
    else:
        result = refresh(selected, cursor="123:0:0")
        assert result["accepted_count"] == 1 and result["next_cursor"] == "456:0:0" and len(calls) == 2


def test_selected_projects_exposes_consent_revision(selected):
    setup, conn, _, _ = selected
    page = gt.selected_projects(setup[0], setup[1][1], setup[1][2].get_uid(), conn["connection_uid"])
    assert page["binding"]["granted_capabilities"] == ["resources.read", "signals.read"]
    with DbSession.use(readonly=False) as db:
        binding = db.exec(SqlBuilder.select.table(BoardAppBinding)).first()
        assert page["binding"]["revision"] == binding.edit_revision()
        assert not binding.stage_transitions_enabled


@pytest.mark.parametrize("change", ["disabled", "capability"])
@pytest.mark.parametrize("inflight", [False, True])
def test_app_registry_revocation_fences_refresh(selected, change, inflight):
    from langboard_shared.domain.models import AppDefinition

    setup = selected[0]
    board = setup[1]
    with DbSession.atomic() as db:
        definition = AppDefinition(key="glitchtip", approved_by=board[1].id, declaration={"capabilities": ["signals.read"]})
        db.insert(definition)

    def revoke():
        with DbSession.atomic() as db:
            current = db.exec(SqlBuilder.select.table(AppDefinition).where(AppDefinition.key == "glitchtip")).first()
            if change == "disabled":
                current.is_enabled = False
            else:
                current.declaration = {"capabilities": []}
            db.update(current)

    if inflight:
        setup[-1]["after_issues"] = revoke
    else:
        revoke()
    with pytest.raises(gt.GlitchTipUnavailable):
        refresh(selected)
    with DbSession.use(readonly=False) as db:
        assert not db.exec(SqlBuilder.select.table(AppSignal)).all()
