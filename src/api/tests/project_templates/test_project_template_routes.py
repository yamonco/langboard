import os
from types import SimpleNamespace
from typing import Any, Callable
import pytest
from fastapi import HTTPException


os.environ.setdefault("PROJECT_NAME", "langboard")

from langboard.routes.board.BoardSettingApi import copy_project_as_template
from langboard.routes.board.forms import CopyProjectTemplateForm
from langboard.routes.dashboard.DashboardApi import create_project
from langboard.routes.dashboard.DashboardForm import DashboardProjectCreateForm
from langboard.routes.settings.Form import SetDefaultProjectTemplateForm
from langboard.routes.settings.ProjectTemplateSettingsApi import set_default_project_template


class _FailingProjectTemplateService:
    def set_default(self, *_args: Any) -> None:
        raise ValueError("invalid template")

    def create_project(self, *_args: Any) -> None:
        raise ValueError("invalid template")

    def copy_from_project(self, *_args: Any) -> None:
        raise ValueError("invalid template")


def test_invalid_template_inputs_use_the_native_bad_request_contract() -> None:
    service = SimpleNamespace(
        project_template=_FailingProjectTemplateService(),
        project=SimpleNamespace(get_by_id_like=lambda _uid: object()),
    )
    calls: tuple[Callable[[], Any], ...] = (
        lambda: set_default_project_template(SetDefaultProjectTemplateForm(template_name="missing"), service),
        lambda: create_project(
            DashboardProjectCreateForm(title="Project", template_name="missing"),
            object(),
            service,
        ),
        lambda: copy_project_as_template(
            "project",
            CopyProjectTemplateForm(name="duplicate"),
            service,
        ),
    )

    for call in calls:
        with pytest.raises(HTTPException) as caught:
            call()
        assert caught.value.status_code == 400
        assert caught.value.detail["code"] == "VA0000"
