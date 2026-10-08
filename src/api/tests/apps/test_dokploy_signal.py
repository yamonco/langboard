# ruff: noqa: F811
"""Actual storage/capability fences with official deployment metadata contracts."""

import json
import pytest
from langboard.apps import DokployConnection as dk
from langboard.apps import DokploySignal as signal
from langboard_shared.core.db import DbSession, SqlBuilder
from langboard_shared.core.db.DbEngine import DbEngine
from langboard_shared.domain.models import AppResourceBinding, AppSignal, BoardAppBinding
from langboard_shared.domain.services.factory.SecretReferenceService_test import secrets  # noqa: F401
from langboard_shared.domain.services.factory.WorkflowStageService_app_test import board  # noqa: F401
from langboard_shared.publishers import CardPublisher
from test_dokploy_connection import connect, setup  # noqa: F401


@pytest.fixture(params=["application", "compose"])
def selected(setup, monkeypatch, request):
    service, board, _, _, state = setup
    kind = request.param
    external_id = "app-1" if kind == "application" else "compose-1"
    connection = connect(setup)
    chosen = dk.bind_resource(
        service,
        board[1],
        board[2].get_uid(),
        connection["connection_uid"],
        kind,
        external_id,
        "project-1",
        "env-1",
        connection["revision"],
    )
    with DbSession.use(readonly=False) as db:
        AppSignal.__table__.create(DbEngine.get_main_engine(), checkfirst=True)
        binding = db.exec(SqlBuilder.select.table(BoardAppBinding)).first()
        binding.state, binding.granted_capabilities = "enabled", ["signals.read", "deployments.read"]
        db.update(binding)
    state["rows"] = [
        {
            "deploymentId": "dep-1",
            kind + "Id": external_id,
            "status": "done",
            "createdAt": "2026-10-08T10:00:00Z",
            "finishedAt": "2026-10-08T10:01:00Z",
            "errorMessage": "private",
            "logPath": "/private/log",
            "pid": "42",
        }
    ]
    original_get = signal.read_json

    def deployment_get(base, path, headers, params=None):
        endpoint = "/api/deployment.all" if kind == "application" else "/api/deployment.allByCompose"
        if path == endpoint:
            assert params == {kind + "Id": external_id} and headers["x-api-key"] == "fixture-api-key"
            if state.get("after_deploy"):
                state["after_deploy"]()
            return state["rows"], {}
        return original_get(base, path, headers, params)

    monkeypatch.setattr(signal, "read_json", deployment_get)
    events = []
    monkeypatch.setattr(CardPublisher, "app_signal_changed", lambda uid: events.append(uid))
    return setup, connection, chosen, events


def refresh(selected):
    setup, connection, chosen, _ = selected
    service, board, *_ = setup
    return signal.refresh_deployments(
        service,
        board[1],
        board[2].get_uid(),
        connection["connection_uid"],
        chosen["resource_uid"],
        connection["revision"],
        chosen["access_revision"],
    )


def test_append_only_safe_idempotent_refresh(selected):
    setup, connection, chosen, events = selected
    first = refresh(selected)
    assert first["inserted"] == 1 and not first["truncated"]
    assert first["items"][0]["event_type"] == "deployment.succeeded"
    assert "private" not in json.dumps(first) and "42" not in json.dumps(first)
    assert refresh(selected)["inserted"] == 0 and len(events) == 1
    with DbSession.use(readonly=False) as db:
        rows = db.exec(SqlBuilder.select.table(AppSignal)).all()
        assert len(rows) == 1 and rows[0].commit_sha == ""
        assert "private" not in json.dumps(rows[0].model_dump(), default=str)
        binding = db.exec(SqlBuilder.select.table(BoardAppBinding)).first()
        assert not binding.stage_transitions_enabled and binding.workflow_mapping == {}


def test_refresh_reports_bounded_latest_page(selected):
    state = selected[0][4]
    template = state["rows"][0]
    state["rows"] = [
        {**template, "deploymentId": f"dep-{i}", "finishedAt": f"2026-10-08T10:{i:02}:00Z"} for i in range(30)
    ]
    result = refresh(selected)
    assert result["truncated"] and result["limit"] == 25 and result["inserted"] == 25
    assert [row["external_id"] for row in result["items"]] == [f"dep-{i}" for i in range(29, 4, -1)]
    assert refresh(selected)["inserted"] == 0


def test_malformed_batch_leaves_no_partial_evidence(selected):
    state = selected[0][4]
    state["rows"].append({**state["rows"][0], "deploymentId": "bad", "status": []})
    with pytest.raises(dk.DokployUnavailable):
        refresh(selected)
    with DbSession.use(readonly=False) as db:
        assert not db.exec(SqlBuilder.select.table(AppSignal)).all()
    assert not selected[3]


def test_lifecycle_appends_without_overwriting_prior_signal(selected):
    row = selected[0][4]["rows"][0]
    row["status"], row["startedAt"] = "running", "2026-10-08T10:00:10Z"
    assert refresh(selected)["items"][0]["event_type"] == "deployment.started"
    row["status"] = "done"
    assert refresh(selected)["inserted"] == 1
    with DbSession.use(readonly=False) as db:
        rows = db.exec(SqlBuilder.select.table(AppSignal)).all()
        assert {row.event_type for row in rows} == {"deployment.started", "deployment.succeeded"}
    assert len(selected[3]) == 2


@pytest.mark.parametrize("failure", ["capability", "disabled", "unselected", "revoked", "revision"])
def test_current_gate_rejects_before_provider_io(selected, failure):
    setup, _, _, _ = selected
    with DbSession.use(readonly=False) as db:
        binding = db.exec(SqlBuilder.select.table(BoardAppBinding)).first()
        resource = db.exec(SqlBuilder.select.table(AppResourceBinding)).first()
        if failure == "capability":
            binding.granted_capabilities = ["signals.read"]
        elif failure == "disabled":
            binding.state = "disabled"
        elif failure == "unselected":
            resource.is_selected = False
        elif failure == "revoked":
            resource.access_state = "revoked"
        else:
            resource.access_revision += 1
        db.update(binding)
        db.update(resource)
    before = len(setup[3])
    with pytest.raises((dk.DokployUnavailable, dk.DokployConflict)):
        refresh(selected)
    assert len(setup[3]) == before


@pytest.mark.parametrize("failure", ["capability", "unselected", "revision"])
def test_inflight_binding_changes_do_not_write_signals(selected, failure):
    setup, _, _, events = selected

    def change():
        with DbSession.use(readonly=False) as db:
            binding = db.exec(SqlBuilder.select.table(BoardAppBinding)).first()
            resource = db.exec(SqlBuilder.select.table(AppResourceBinding)).first()
            if failure == "capability":
                binding.granted_capabilities = []
            elif failure == "unselected":
                resource.is_selected = False
            else:
                resource.access_revision += 1
            db.update(binding)
            db.update(resource)

    setup[4]["after_deploy"] = change
    with pytest.raises((dk.DokployUnavailable, dk.DokployConflict)):
        refresh(selected)
    with DbSession.use(readonly=False) as db:
        assert not db.exec(SqlBuilder.select.table(AppSignal)).all()
    assert not events


@pytest.mark.parametrize(
    "status,started,finished,event",
    [
        ("running", None, None, "deployment.queued"),
        ("running", "2026-10-08T10:00:10Z", None, "deployment.started"),
        ("done", None, "2026-10-08T10:01:00Z", "deployment.succeeded"),
        ("error", None, "2026-10-08T10:01:00Z", "deployment.failed"),
        ("cancelled", None, "2026-10-08T10:01:00Z", "deployment.cancelled"),
    ],
)
def test_official_state_and_timestamp_semantics(status, started, finished, event):
    row = {
        "deploymentId": "dep-1",
        "applicationId": "app-1",
        "status": status,
        "createdAt": "2026-10-08T10:00:00Z",
        "startedAt": started,
        "finishedAt": finished,
    }
    assert signal.normalize_deployment(row, "application", "app-1")["event_type"] == event


@pytest.mark.parametrize(
    "mutation",
    [
        {"status": "unknown"},
        {"status": []},
        {"finishedAt": None},
        {"finishedAt": "2026-10-08T10:01:00"},
        {"applicationId": "foreign"},
    ],
)
def test_invalid_evidence_has_no_fallback_timestamp(mutation):
    row = {
        "deploymentId": "dep-1",
        "applicationId": "app-1",
        "status": "done",
        "createdAt": "2026-10-08T10:00:00Z",
        "finishedAt": "2026-10-08T10:01:00Z",
        **mutation,
    }
    with pytest.raises(dk.DokployUnavailable):
        signal.normalize_deployment(row, "application", "app-1")
