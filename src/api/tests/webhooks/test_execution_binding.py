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


def test_disabled_binding_never_requires_a_target() -> None:
    BoardSettingApi._validate_execution_binding(
        SimpleNamespace(id=1), UpdateProjectExecutionBindingForm(is_enabled=False)
    )
