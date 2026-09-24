import os
from types import SimpleNamespace
import pytest


os.environ.setdefault("PROJECT_NAME", "langboard")

from langboard.routes.board import BoardSettingApi  # noqa: E402
from langboard.routes.board.forms.Project import UpdateProjectExecutionBindingForm  # noqa: E402
from langboard_shared.domain.models import (  # noqa: E402
    GlobalCardRelationshipType,
    ProjectColumn,
    WebhookSetting,
)


def test_enabled_binding_checks_board_scope_and_explicit_webhook(monkeypatch: pytest.MonkeyPatch) -> None:
    project = SimpleNamespace(id=1)
    records = {
        (ProjectColumn, "ready"): SimpleNamespace(project_id=1, is_archive=False),
        (ProjectColumn, "done"): SimpleNamespace(project_id=1, is_archive=False),
        (GlobalCardRelationshipType, "prerequisite"): object(),
        (WebhookSetting, "hook"): SimpleNamespace(events=["io.langboard.work.ready.v1"], secret_id="key"),
    }
    monkeypatch.setattr(
        BoardSettingApi.InfraHelper,
        "get_by_id_like",
        lambda model, uid: records.get((model, uid)),
    )
    form = UpdateProjectExecutionBindingForm(
        is_enabled=True,
        column_semantics={"ready": "ready", "done": "terminal"},
        prerequisite_relationship_type_uid="prerequisite",
        webhook_uid="hook",
        events=["io.langboard.work.ready.v1"],
    )
    BoardSettingApi._validate_execution_binding(project, form)

    records[(ProjectColumn, "ready")] = SimpleNamespace(project_id=2, is_archive=False)
    with pytest.raises(ValueError, match="active board"):
        BoardSettingApi._validate_execution_binding(project, form)
    records[(ProjectColumn, "ready")] = SimpleNamespace(project_id=1, is_archive=False)

    records[(WebhookSetting, "hook")] = SimpleNamespace(events=None)
    with pytest.raises(ValueError, match="explicitly allow"):
        BoardSettingApi._validate_execution_binding(project, form)


def test_live_binding_rechecks_webhook_and_signing_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    from langboard_shared.domain.models import Project
    from langboard_shared.tasks.webhooks import ExecutionBindingPolicy

    event = "io.langboard.work.ready.v1"
    binding = SimpleNamespace(
        project_id=1,
        is_enabled=True,
        events=[event],
        webhook_uid="hook",
        webhook_id=7,
        column_semantics={"ready": "ready", "done": "terminal"},
        column_semantic_ids={"2": "ready", "3": "terminal"},
        prerequisite_relationship_type_uid="prerequisite",
        prerequisite_relationship_type_id=8,
    )
    records = {
        (Project, 1): SimpleNamespace(id=1),
        (ProjectColumn, "ready"): SimpleNamespace(id=2, project_id=1, is_archive=False, deleted_at=None),
        (ProjectColumn, "done"): SimpleNamespace(id=3, project_id=1, is_archive=False, deleted_at=None),
        (GlobalCardRelationshipType, "prerequisite"): SimpleNamespace(id=8),
        (WebhookSetting, "hook"): SimpleNamespace(id=7, events=[event], secret_id="key"),
    }
    monkeypatch.setattr(ExecutionBindingPolicy.InfraHelper, "get_by_id_like", lambda model, uid: records.get((model, uid)))
    monkeypatch.setattr(ExecutionBindingPolicy.KeyVault, "get_key", lambda key: "secret")
    assert ExecutionBindingPolicy.binding_invalid_reasons(binding, event) == []
    records.pop((WebhookSetting, "hook"))
    assert "webhook_missing" in ExecutionBindingPolicy.binding_invalid_reasons(binding, event)
    records[(WebhookSetting, "hook")] = SimpleNamespace(id=7, events=[], secret_id="key")
    assert "event_not_allowed" in ExecutionBindingPolicy.binding_invalid_reasons(binding, event)
    records[(WebhookSetting, "hook")] = SimpleNamespace(id=7, events=[event], secret_id=None)
    assert "signing_secret_missing" in ExecutionBindingPolicy.binding_invalid_reasons(binding, event)


@pytest.mark.asyncio
async def test_invalid_execution_binding_never_schedules_delivery(monkeypatch: pytest.MonkeyPatch) -> None:
    from langboard_shared.tasks.webhooks import WebhookTask
    from langboard_shared.tasks.webhooks.utils import WebhookModel

    queued = []
    monkeypatch.setattr(WebhookTask, "binding_for_project", lambda project_uid: None)
    monkeypatch.setattr(WebhookTask, "webhook_delivery_task", lambda *args: queued.append(args))
    model = WebhookModel(event="io.langboard.work.ready.v1", data={
        "project_uid": "p", "card_uid": "c", "execution_generation": 1,
        "title": "Task", "card_url": "/board/p/c", "source_revision": "r",
    })
    await WebhookTask.run_webhook(model)
    assert queued == []


@pytest.mark.asyncio
async def test_deleted_binding_target_cannot_deliver_queued_event(monkeypatch: pytest.MonkeyPatch) -> None:
    from langboard_shared.tasks.webhooks import WebhookTask
    from langboard_shared.tasks.webhooks.utils import WebhookModel

    monkeypatch.setattr(WebhookTask, "_get_webhook_setting", lambda uid: SimpleNamespace(events=["io.langboard.work.ready.v1"]))
    monkeypatch.setattr(WebhookTask, "binding_for_project", lambda project_uid: None)
    model = WebhookModel(event="io.langboard.work.ready.v1", data={
        "project_uid": "p", "card_uid": "c", "execution_generation": 1,
        "title": "Task", "card_url": "/board/p/c", "source_revision": "r",
    })
    await WebhookTask.deliver_webhook(model, "deleted-hook")


def _deliver_harness(monkeypatch: pytest.MonkeyPatch, current) -> dict:
    """Patch one execution delivery run; return the payload captured at signing time."""
    from contextlib import contextmanager
    from datetime import datetime, timezone
    from langboard_shared.tasks.webhooks import ExecutionReadinessUow, WebhookTask

    captured: dict = {}
    occurred_at = datetime(2026, 9, 24, tzinfo=timezone.utc)

    def fake_signed_request(model, secret, *, timestamp=None):
        captured["data"] = model.data
        return b"{}", {"Content-Type": "application/json"}

    class FakeResponse:
        def raise_for_status(self) -> None:
            return None

    class FakeClient:
        def __init__(self, **kwargs) -> None:
            return None

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def post(self, *args, **kwargs):
            return FakeResponse()

    @contextmanager
    def fake_repository():
        yield SimpleNamespace(
            webhook_setting=SimpleNamespace(record_delivery_success=lambda uid, now: None)
        )

    monkeypatch.setattr(WebhookTask, "signed_request", fake_signed_request)
    monkeypatch.setattr(WebhookTask, "AsyncClient", FakeClient)
    async def fake_resolve(url: str):
        return SimpleNamespace(url="https://example.com/hook", host_header="example.com", sni_hostname="example.com")

    monkeypatch.setattr(WebhookTask, "ensure_public_webhook_url", fake_resolve)
    monkeypatch.setattr(WebhookTask.Repository, "use", fake_repository)
    monkeypatch.setattr(
        WebhookTask,
        "_get_webhook_setting",
        lambda uid: SimpleNamespace(events=["io.langboard.work.ready.v1"], secret_id=None, url="https://example.com/hook"),
    )
    monkeypatch.setattr(
        WebhookTask,
        "binding_for_project",
        lambda uid: SimpleNamespace(id=8, updated_at=occurred_at, webhook_uid="hook-40"),
    )
    monkeypatch.setattr(WebhookTask, "binding_invalid_reasons", lambda binding, event: [])
    monkeypatch.setattr(ExecutionReadinessUow, "current_execution", lambda card_id, db=None: current)
    return captured


@pytest.mark.asyncio
async def test_execution_delivery_survives_content_edit_and_signs_latest_content(monkeypatch: pytest.MonkeyPatch) -> None:
    """A READY-preserving edit between drain and delivery must not supersede the event."""
    from datetime import datetime, timezone
    from langboard_shared.tasks.webhooks import WebhookTask
    from langboard_shared.tasks.webhooks.ExecutionReadinessUow import CurrentExecution
    from langboard_shared.tasks.webhooks.utils import WebhookModel

    current = CurrentExecution(
        revision=datetime(2026, 9, 24, 1, tzinfo=timezone.utc),
        is_ready=True,
        generation=5,
        title="Edited at delivery time",
        labels=["reviewer"],
        assignee_ids=[7],
    )
    captured = _deliver_harness(monkeypatch, current)
    model = WebhookModel(event="io.langboard.work.ready.v1", data={
        "project_uid": "p", "card_uid": "c", "execution_generation": 5,
        "title": "Frozen title", "labels": ["frozen-role"], "assignees": [],
        "card_url": "/board/p/c", "source_revision": "2026-09-24T00:00:00+00:00",
    })
    await WebhookTask.deliver_webhook(model, "hook-40", "8", "2026-09-24T00:00:00+00:00")
    assert captured["data"]["title"] == "Edited at delivery time"
    assert captured["data"]["labels"] == ["reviewer"]
    assert captured["data"]["source_revision"] == current.revision.isoformat()
    assert captured["data"]["execution_generation"] == 5


@pytest.mark.asyncio
async def test_execution_delivery_superseded_only_on_lost_readiness_or_new_generation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from datetime import datetime, timezone
    from langboard_shared.tasks.webhooks import WebhookTask
    from langboard_shared.tasks.webhooks.ExecutionReadinessUow import CurrentExecution
    from langboard_shared.tasks.webhooks.utils import WebhookModel

    for current in (
        CurrentExecution(datetime(2026, 9, 24, tzinfo=timezone.utc), False, 5, "Task", [], []),
        CurrentExecution(datetime(2026, 9, 24, tzinfo=timezone.utc), True, 6, "Task", [], []),
    ):
        captured = _deliver_harness(monkeypatch, current)
        model = WebhookModel(event="io.langboard.work.ready.v1", data={
            "project_uid": "p", "card_uid": "c", "execution_generation": 5,
            "title": "Task", "card_url": "/board/p/c", "source_revision": "r",
        })
        await WebhookTask.deliver_webhook(model, "hook-40", "8", "2026-09-24T00:00:00+00:00")
        assert captured == {}


def test_disabled_binding_never_requires_a_target() -> None:
    BoardSettingApi._validate_execution_binding(
        SimpleNamespace(id=1), UpdateProjectExecutionBindingForm(is_enabled=False)
    )
