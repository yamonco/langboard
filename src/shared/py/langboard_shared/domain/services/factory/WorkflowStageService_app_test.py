"""App previews use current primary authority and semantic registry rows."""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from ....core.db import DbSession
from ....core.db.DbEngine import DbEngine
from ....core.types import SafeDateTime
from ...models import Project, ProjectAssignedUser, ProjectColumn, ProjectRole, User, WorkflowStageDefinition
from ..AppWorkflowPolicy import GITHUB_WORKFLOW_REQUIREMENTS
from .WorkflowStageService import WorkflowStageService


@pytest.fixture
def board(monkeypatch):
    engine = create_engine("sqlite://")
    for model in (User, Project, ProjectAssignedUser, ProjectRole, ProjectColumn, WorkflowStageDefinition):
        model.__table__.create(engine)
    monkeypatch.setattr(DbEngine, "get_main_engine", lambda: engine)

    def replica_forbidden():
        raise AssertionError("App preview must not read a stale replica")

    monkeypatch.setattr(DbEngine, "get_readonly_engine", replica_forbidden)
    with Session(engine, expire_on_commit=False) as db:
        user = User(
            id=1,
            firstname="Test",
            lastname="Reader",
            email="reader@example.invalid",
            password="test-only",
            activated_at=SafeDateTime.now(),
        )
        project = Project(id=10, owner_id=2, title="Current board")
        member = ProjectAssignedUser(id=20, project_id=10, user_id=1)
        role = ProjectRole(id=30, project_id=10, user_id=1, actions=["read"])
        columns = [
            ProjectColumn(id=40 + i, project_id=10, name="Localized", workflow_stage=key)
            for i, key in enumerate(("active", "review", "closed"))
        ]
        stages = [
            WorkflowStageDefinition(id=50 + i, key=key, name="Localized")
            for i, key in enumerate(("active", "review", "closed"))
        ]
        for row in (user, project, member, role, *columns, *stages):
            db.add(row)
        db.commit()
    service = WorkflowStageService(lambda _: None, lambda _: None, None)
    try:
        yield service, user, project, member, role, columns, stages
    finally:
        engine.dispose()


def preview(board, explicit=None):
    service, user, project, *_ = board
    return service.preview_app_mapping(user, project, GITHUB_WORKFLOW_REQUIREMENTS, explicit or {})


def test_primary_current_keys_ignore_display_names_and_foreign_columns(board):
    with DbSession.use(readonly=False) as db:
        db.insert(ProjectColumn(project_id=11, name="active", workflow_stage="active"))
    result = preview(board)
    assert result.transitions_enabled
    assert result.choices[0].candidates == (board[5][0].get_uid(),)


@pytest.mark.parametrize("revocation", ["member", "role", "user", "inactive", "project", "admin"])
def test_cached_caller_cannot_survive_current_revocation(board, revocation):
    _, user, project, member, role, *_ = board
    row = {"member": member, "role": role, "user": user, "inactive": user, "project": project, "admin": user}[
        revocation
    ]
    stale_user = user.model_copy(update={"is_admin": revocation == "admin"})
    with DbSession.use(readonly=False) as db:
        if revocation == "member":
            db.delete(row)
        else:
            if revocation == "role":
                row.actions = ["card_update"]
            elif revocation == "inactive":
                row.activated_at = None
            elif revocation == "admin":
                row.is_admin = False
                role.actions = []
                db.update(role)
            else:
                row.deleted_at = SafeDateTime.now()
            db.update(row)
    assert board[0].preview_app_mapping(stale_user, project, GITHUB_WORKFLOW_REQUIREMENTS, {}) is None


@pytest.mark.parametrize("change", ["archive", "deleted", "stage", "registry"])
def test_saved_mapping_uses_current_rows_without_fallback(board, change):
    column, stage = board[5][0], board[6][0]
    chosen = column.get_uid()
    with DbSession.use(readonly=False) as db:
        db.insert(ProjectColumn(project_id=10, name="Duplicate", workflow_stage="active"))
        if change == "archive":
            column.is_archive = True
        elif change == "deleted":
            column.deleted_at = SafeDateTime.now()
        elif change == "stage":
            column.workflow_stage = "review"
        else:
            stage.is_active = False
            db.update(stage)
        db.update(column)
    result = preview(board, {"active": chosen})
    assert not result.transitions_enabled
    assert result.choices[0].status == "invalid"
    assert result.choices[0].column_uid is None


@pytest.mark.parametrize("authority", ["owner", "admin"])
def test_current_owner_or_admin_can_preview_without_membership(board, authority):
    _, user, project, member, role, *_ = board
    with DbSession.use(readonly=False) as db:
        db.delete(member)
        db.delete(role)
        if authority == "owner":
            project.owner_id = user.id
            db.update(project)
        else:
            user.is_admin = True
            db.update(user)
    assert preview(board).transitions_enabled


def test_stale_project_owner_and_unknown_actor_do_not_grant_access(board):
    service, user, project, member, *_ = board
    with DbSession.use(readonly=False) as db:
        db.delete(member)
    stale_project = project.model_copy(update={"owner_id": user.id})
    assert service.preview_app_mapping(user, stale_project, GITHUB_WORKFLOW_REQUIREMENTS, {}) is None
    assert service.preview_app_mapping(None, project, GITHUB_WORKFLOW_REQUIREMENTS, {}) is None
