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
        (WebhookSetting, "hook"): SimpleNamespace(events=["io.langboard.work.ready.v1"]),
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


def test_disabled_binding_never_requires_a_target() -> None:
    BoardSettingApi._validate_execution_binding(
        SimpleNamespace(id=1), UpdateProjectExecutionBindingForm(is_enabled=False)
    )
