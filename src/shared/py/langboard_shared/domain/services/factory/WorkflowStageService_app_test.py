"""App previews use current primary authority and semantic registry rows."""

import os
from uuid import uuid4
import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session
from ....core.db import DbSession
from ....core.db.DbEngine import DbEngine
from ....core.types import SafeDateTime
from ...models import (
    BoardAppBinding,
    Project,
    ProjectAssignedUser,
    ProjectColumn,
    ProjectRole,
    User,
    WorkflowStageDefinition,
)
from ..AppWorkflowPolicy import GITHUB_WORKFLOW_REQUIREMENTS
from .WorkflowStageService import WorkflowStageService


@pytest.fixture(params=["sqlite://", "postgresql-test"])
def board(monkeypatch, request):
    url = request.param
    if url == "postgresql-test":
        url = os.environ.get("LANGBOARD_FILE_TEST_DATABASE_URL")
        if not url:
            pytest.skip("Set LANGBOARD_FILE_TEST_DATABASE_URL to a disposable PostgreSQL database")
    engine = create_engine(url)
    schema = None
    if engine.dialect.name == "postgresql":
        schema = "app_authority_test_" + uuid4().hex
        with engine.begin() as db:
            db.execute(text(f'CREATE SCHEMA "{schema}"'))
        engine.dispose()
        engine = create_engine(url, connect_args={"options": f"-csearch_path={schema}"})
        with engine.begin() as db:
            db.execute(text("CREATE TABLE organization (id BIGINT PRIMARY KEY)"))
    for model in (
        User,
        Project,
        ProjectAssignedUser,
        ProjectRole,
        ProjectColumn,
        WorkflowStageDefinition,
        BoardAppBinding,
    ):
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
        owner = User(
            id=2,
            firstname="Test",
            lastname="Owner",
            email="owner@example.invalid",
            password="test-only",
            activated_at=SafeDateTime.now(),
        )
        db.add_all([user, owner])
        db.commit()
        project = Project(id=10, owner_id=2, title="Current board")
        db.add_all([project, Project(id=11, owner_id=2, title="Foreign board")])
        db.commit()
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
        for row in (member, role, *columns, *stages):
            db.add(row)
        db.commit()
    service = WorkflowStageService(lambda _: None, lambda _: None, None)
    try:
        yield service, user, project, member, role, columns, stages
    finally:
        if schema:
            with engine.begin() as db:
                db.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
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


@pytest.fixture
def binding(board):
    with DbSession.use(readonly=False) as db:
        row = BoardAppBinding(project_id=10, app_key="github", state="enabled", granted_capabilities=["signals.read"])
        db.insert(row)
        board[4].actions = ["read", "update"]
        db.update(board[4])
    return row


def save_mapping(board, binding, mapping=None, enabled=True, revision=None):
    return board[0].save_app_mapping(
        board[1],
        binding.get_uid(),
        mapping,
        project_uid=board[2].get_uid(),
        app_key=binding.app_key,
        expected_revision=revision or binding.edit_revision(),
        enable_transitions=enabled,
    )


def test_saved_auto_choices_survive_duplicates_and_keep_activation_grants(board, binding):
    saved = save_mapping(board, binding)
    assert saved.stage_transitions_enabled
    assert saved.workflow_mapping == {key: col.get_uid() for key, col in zip(("active", "review", "closed"), board[5])}
    with DbSession.use(readonly=False) as db:
        db.insert(ProjectColumn(project_id=10, name="New", workflow_stage="active"))
    again = save_mapping(board, saved)
    assert again.workflow_mapping == saved.workflow_mapping
    assert again.state == "enabled" and again.granted_capabilities == ["signals.read"]


@pytest.mark.parametrize("revoked", ["role", "membership", "inactive"])
def test_write_gate_uses_current_authority_and_leaves_mapping_unchanged(board, binding, revoked):
    with DbSession.use(readonly=False) as db:
        if revoked == "membership":
            db.delete(board[3])
        elif revoked == "role":
            board[4].actions = ["read"]
            db.update(board[4])
        else:
            board[1].activated_at = None
            db.update(board[1])
    assert save_mapping(board, binding) is None
    with DbSession.use(readonly=False) as db:
        from ....core.db import SqlBuilder

        current = db.exec(SqlBuilder.select.table(BoardAppBinding).where(BoardAppBinding.id == binding.id)).first()
    assert current.workflow_mapping == {} and not current.stage_transitions_enabled


def test_incomplete_mapping_can_be_saved_only_without_transition(board, binding):
    with DbSession.use(readonly=False) as db:
        board[5][0].workflow_stage = None
        db.update(board[5][0])
    with pytest.raises(ValueError, match="incomplete"):
        save_mapping(board, binding)
    saved = save_mapping(board, binding, enabled=False)
    assert not saved.stage_transitions_enabled and "active" not in saved.workflow_mapping


def test_stale_revision_never_overwrites_saved_choices(board, binding):
    from .WorkflowStageService import WorkflowStageEditConflict

    old = binding.edit_revision()
    saved = save_mapping(board, binding)
    with pytest.raises(WorkflowStageEditConflict):
        save_mapping(board, saved, {}, enabled=False, revision=old)


def test_deleted_target_never_replaced_on_enable(board, binding):
    saved = save_mapping(board, binding)
    with DbSession.use(readonly=False) as db:
        db.delete(board[5][0])
        db.insert(ProjectColumn(project_id=10, name="Replacement", workflow_stage="active"))
    with pytest.raises(ValueError, match="incomplete"):
        save_mapping(board, saved)
    disabled = save_mapping(board, saved, enabled=False)
    assert disabled.workflow_mapping["active"] == board[5][0].get_uid()
    assert not disabled.stage_transitions_enabled


def test_unknown_app_cannot_save_or_enable_with_an_invented_contract(board, binding):
    with DbSession.use(readonly=False) as db:
        binding.app_key = "unregistered"
        db.update(binding)
    assert save_mapping(board, binding) is None


def test_glitchtip_saved_binding_uses_its_own_optional_contract(board, binding):
    with DbSession.use(readonly=False) as db:
        binding.app_key = "glitchtip"
        db.update(binding)
    with pytest.raises(ValueError, match="undeclared"):
        save_mapping(board, binding, {"ready": "arbitrary"})
    assert save_mapping(board, binding).stage_transitions_enabled


def test_postgresql_concurrent_edit_has_one_winner(board, binding):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    from .WorkflowStageService import WorkflowStageEditConflict

    if DbEngine.get_main_engine().dialect.name != "postgresql":
        pytest.skip("Row-lock concurrency requires PostgreSQL")
    ready = Barrier(2)
    revision = binding.edit_revision()

    def attempt():
        ready.wait(timeout=5)
        try:
            saved = save_mapping(board, binding, revision=revision)
            return "saved" if saved else "denied"
        except WorkflowStageEditConflict:
            return "conflict"

    with ThreadPoolExecutor(max_workers=2) as workers:
        results = [workers.submit(attempt) for _ in range(2)]
        assert sorted(result.result(timeout=15) for result in results) == ["conflict", "saved"]
