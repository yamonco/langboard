# ruff: noqa: F811
"""Registered App routes exercise current DB authority and saved revisions."""

import json
from types import SimpleNamespace
import pytest
from langboard.routes.board.BoardSettingApi import (
    AppWorkflowMappingForm,
    get_app_workflow_mapping,
    update_app_workflow_mapping,
)
from langboard_shared.core.db import DbSession
from langboard_shared.core.routing import ApiException
from langboard_shared.domain.services.factory.WorkflowStageService_app_test import binding, board  # noqa: F401
from pydantic import ValidationError


def service(board):
    return SimpleNamespace(workflow_stage=board[0])


def form(binding, mapping=None, revision=None):
    return AppWorkflowMappingForm(
        binding_uid=binding.get_uid(),
        workflow_mapping=mapping,
        expected_revision=revision or binding.edit_revision(),
        enable_transitions=True,
    )


def test_route_reads_and_saves_persisted_mapping(board, binding):
    response = get_app_workflow_mapping(board[2].get_uid(), "github", board[1], service(board))
    data = json.loads(response.body)
    assert data["mapping_valid"] and data["binding"]["revision"] == binding.edit_revision()
    response = update_app_workflow_mapping(board[2].get_uid(), "github", form(binding), board[1], service(board))
    data = json.loads(response.body)
    assert data["binding"]["stage_transitions_enabled"]
    assert len(data["binding"]["workflow_mapping"]) == 3
    with pytest.raises(ApiException.Conflict_409):
        update_app_workflow_mapping(board[2].get_uid(), "github", form(binding), board[1], service(board))


def test_foreign_board_binding_and_app_path_cannot_write(board, binding):
    for project, app in [("b", "github"), (board[2].get_uid(), "glitchtip")]:
        with pytest.raises(ApiException.NotFound_404):
            update_app_workflow_mapping(project, app, form(binding), board[1], service(board))


def test_read_grant_does_not_allow_settings_write(board, binding):
    with DbSession.use(readonly=False) as db:
        board[4].actions = ["read"]
        db.update(board[4])
    assert get_app_workflow_mapping(board[2].get_uid(), "github", board[1], service(board)).status_code == 200
    with pytest.raises(ApiException.NotFound_404):
        update_app_workflow_mapping(board[2].get_uid(), "github", form(binding), board[1], service(board))


@pytest.mark.parametrize("extra", [{"requirements": {"required": ["active"]}}, {"authorized_column_ids": [40]}])
def test_form_rejects_caller_authority(extra):
    with pytest.raises(ValidationError):
        AppWorkflowMappingForm(
            binding_uid="x", workflow_mapping={}, expected_revision="a" * 64, enable_transitions=True, **extra
        )
