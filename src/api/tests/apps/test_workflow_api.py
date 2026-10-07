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
    assert data["column_names"] == {column.get_uid(): column.name for column in board[5]}
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


def test_repair_columns_exclude_foreign_deleted_and_archive(board):
    from langboard_shared.core.types import SafeDateTime
    from langboard_shared.domain.models import ProjectColumn

    with DbSession.use(readonly=False) as db:
        unclassified = ProjectColumn(project_id=10, name="Unclassified")
        db.insert(unclassified)
        db.insert(ProjectColumn(project_id=11, name="Foreign"))
        db.insert(ProjectColumn(project_id=10, name="Archive", is_archive=True))
        db.insert(ProjectColumn(project_id=10, name="Deleted", deleted_at=SafeDateTime.now()))
    data = json.loads(get_app_workflow_mapping(board[2].get_uid(), "github", board[1], service(board)).body)
    assert {column["uid"] for column in data["available_columns"]} == {column.get_uid() for column in board[5]} | {
        unclassified.get_uid()
    }
    assert {"uid": unclassified.get_uid(), "name": "Unclassified", "workflow_stage": None} in data["available_columns"]


def test_create_column_forwards_stage_and_rejects_inactive_stage():
    from unittest.mock import Mock
    from langboard.routes.board.BoardColumnApi import create_project_column
    from langboard.routes.board.forms.Column import CreateColumnForm

    create = Mock(return_value=SimpleNamespace(api_response=lambda: {"uid": "created", "workflow_stage": "active"}))
    services = SimpleNamespace(project_column=SimpleNamespace(create=create))
    actor = object()
    response = create_project_column("board", CreateColumnForm(name="Doing", workflow_stage="active"), actor, services)
    assert response.status_code == 201
    create.assert_called_once_with(actor, "board", "Doing", description="", workflow_stage="active")
    create.side_effect = ValueError("Inactive workflow stage")
    with pytest.raises(ApiException.BadRequest_400):
        create_project_column("board", CreateColumnForm(name="Doing", workflow_stage="active"), actor, services)


def test_stage_compare_uses_locked_current_row_and_preserves_changes(board, monkeypatch):
    from langboard_shared.core.db.DbEngine import DbEngine
    from langboard_shared.domain.models.ProjectColumn import ProjectColumnWorkflowConflict
    from langboard_shared.domain.services.factory.ProjectColumnService import ProjectColumnService
    from langboard_shared.infrastructure.repositories import Repository
    monkeypatch.setattr(DbEngine, "get_readonly_engine", DbEngine.get_main_engine)
    columns = ProjectColumnService(lambda _: None, lambda _: None, Repository())
    column = board[5][0]
    with pytest.raises(ProjectColumnWorkflowConflict):
        columns.change_workflow_stage(board[2].get_uid(), column.get_uid(), "review",
                                     check_expected=True, expected_workflow_stage=None)
    # A matching no-op needs no readiness side effects or external publishing.
    assert columns.change_workflow_stage(board[2].get_uid(), column.get_uid(), "active",
                                       check_expected=True, expected_workflow_stage="active")
    with DbSession.use(readonly=False) as db:
        from langboard_shared.core.db import SqlBuilder
        from langboard_shared.domain.models import ProjectColumn
        stored = db.exec(SqlBuilder.select.table(ProjectColumn).where(ProjectColumn.id == column.id)).first()
        assert stored.workflow_stage == "active"


@pytest.mark.parametrize("board", ["postgresql-test"], indirect=True)
def test_native_column_stage_concurrent_edit_has_one_winner(board, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    from langboard_shared.core.db.DbEngine import DbEngine
    from langboard_shared.domain.models import Card, ProjectColumn
    from langboard_shared.domain.models.ProjectColumn import ProjectColumnWorkflowConflict
    from langboard_shared.domain.services.factory.ProjectColumnService import ProjectColumnService
    from langboard_shared.helpers import InfraHelper
    from langboard_shared.infrastructure.repositories import Repository
    from langboard_shared.publishers import ProjectColumnPublisher
    from sqlalchemy import select

    engine = DbEngine.get_main_engine()
    Card.__table__.create(engine)
    monkeypatch.setattr(DbEngine, "get_readonly_engine", DbEngine.get_main_engine)
    ready = Barrier(2)
    native_lookup = InfraHelper.get_records_with_foreign_by_params

    def synchronized_lookup(*args, **kwargs):
        result = native_lookup(*args, **kwargs)
        ready.wait(timeout=5)
        return result

    # Both commands finish their native initial lookup before either enters the
    # write transaction. Only the locked current row may decide the expectation.
    monkeypatch.setattr(InfraHelper, "get_records_with_foreign_by_params", synchronized_lookup)
    published = []
    monkeypatch.setattr(ProjectColumnPublisher, "workflow_stage_changed", lambda *args: published.append(args))
    work_states = []
    card_service = SimpleNamespace(publish_work_states=lambda *args: work_states.append(args))
    columns = ProjectColumnService(lambda _: card_service, lambda _: None, Repository())

    def attempt(stage):
        try:
            saved = columns.change_workflow_stage(
                board[2].get_uid(), board[5][0].get_uid(), stage,
                check_expected=True, expected_workflow_stage="active",
            )
            return "saved" if saved else "denied", stage
        except ProjectColumnWorkflowConflict:
            return "conflict", stage

    with ThreadPoolExecutor(max_workers=2) as workers:
        futures = [workers.submit(attempt, stage) for stage in ("review", "closed")]
        results = [future.result(timeout=15) for future in futures]
    assert sorted(result[0] for result in results) == ["conflict", "saved"]
    winner = next(stage for result, stage in results if result == "saved")
    with engine.connect() as connection:
        assert connection.execute(
            select(ProjectColumn.__table__.c.workflow_stage).where(ProjectColumn.__table__.c.id == board[5][0].id)
        ).scalar_one() == winner
    assert len(published) == len(work_states) == 1
    assert published[0][1].workflow_stage == winner
    assert work_states[0][1] == []


def test_native_stage_route_conflict_is_409():
    from unittest.mock import Mock
    from langboard.routes.board.BoardColumnApi import update_project_column_workflow_stage
    from langboard.routes.board.forms.Column import ColumnWorkflowStageForm
    from langboard_shared.domain.models.ProjectColumn import ProjectColumnWorkflowConflict
    change = Mock(side_effect=ProjectColumnWorkflowConflict())
    with pytest.raises(ApiException.Conflict_409):
        update_project_column_workflow_stage("board", "column",
            ColumnWorkflowStageForm(workflow_stage="active", expected_workflow_stage=None),
            SimpleNamespace(project_column=SimpleNamespace(change_workflow_stage=change)))
    change.assert_called_once_with("board", "column", "active", check_expected=True, expected_workflow_stage=None)
