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
from langboard_shared.domain.models import SettingRole
from langboard_shared.domain.models.SettingRole import SettingRoleAction
from langboard_shared.filter import RoleFilter


class _FailingProjectTemplateService:
    def set_default(self, *_args: Any) -> None:
        raise ValueError("invalid template")

    def create_project(self, *_args: Any) -> None:
        raise ValueError("invalid template")

    def copy_from_project(self, *_args: Any) -> None:
        raise ValueError("invalid template")


def test_default_template_update_requires_the_setting_role() -> None:
    role_model, actions, _, allowed_all_admin = RoleFilter.get_filtered(set_default_project_template)

    assert role_model is SettingRole
    assert actions == [SettingRoleAction.ProjectTemplateUpdate.value]
    assert allowed_all_admin is False


def test_invalid_template_inputs_use_the_native_bad_request_contract() -> None:
    service = SimpleNamespace(
        project_template=_FailingProjectTemplateService(),
        project=SimpleNamespace(get_by_id_like=lambda _uid: object()),
        user=SimpleNamespace(
            get_setting_role=lambda _user: SimpleNamespace(
                is_granted=lambda action: action is SettingRoleAction.ProjectTemplateCreate
            )
        ),
    )
    user = SimpleNamespace(email="template-admin@example.com")
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
            user,
            service,
        ),
    )

    for call in calls:
        with pytest.raises(HTTPException) as caught:
            call()
        assert caught.value.status_code == 400
        assert caught.value.detail["code"] == "VA0000"


def test_copy_project_as_template_requires_the_create_setting_role() -> None:
    user = SimpleNamespace(email="template-admin@example.com")
    service = SimpleNamespace(
        user=SimpleNamespace(get_setting_role=lambda _user: SimpleNamespace(is_granted=lambda _action: False))
    )

    with pytest.raises(HTTPException) as caught:
        copy_project_as_template(
            "project",
            CopyProjectTemplateForm(name="Template"),
            user,
            service,
        )

    assert caught.value.status_code == 403
    assert caught.value.detail["code"] == "AU1001"
