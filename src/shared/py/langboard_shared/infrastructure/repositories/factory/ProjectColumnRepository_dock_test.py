"""Shared dock persistence preserves board order and rejects foreign targets."""

import importlib.util
from pathlib import Path
import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import Column, Integer, MetaData, Table, create_engine, inspect, select
from ....core.db import DbSession, SqlBuilder
from ....core.db.DbEngine import DbEngine
from ....domain.models import Project, ProjectColumn, User
from .ProjectColumnRepository import ProjectColumnRepository


@pytest.fixture
def dock(monkeypatch: pytest.MonkeyPatch):
    engine = create_engine("sqlite://")
    for model in (User, Project, ProjectColumn):
        model.__table__.create(engine)
    monkeypatch.setattr(DbEngine, "get_main_engine", lambda: engine)
    monkeypatch.setattr(DbEngine, "get_readonly_engine", lambda: engine)
    with DbSession.use(readonly=False) as db:
        owner = User(firstname="Dock", lastname="Test", email="dock@example.invalid", password="test-only")
        db.insert(owner)
        project = Project(owner_id=owner.id, title="Dock test")
        foreign = Project(owner_id=owner.id, title="Foreign test")
        db.insert(project)
        db.insert(foreign)
        columns = [ProjectColumn(project_id=project.id, name=f"Column {i}", order=i) for i in range(3)]
        columns += [ProjectColumn(project_id=project.id, name="Archive", order=3, is_archive=True)]
        columns += [ProjectColumn(project_id=foreign.id, name="Foreign", order=0)]
        for column in columns:
            db.insert(column)
    try:
        yield ProjectColumnRepository(lambda _: None, lambda _: None), project, columns
    finally:
        engine.dispose()


def snapshot(project: Project | int):
    with DbSession.use(readonly=True) as db:
        columns = db.exec(
            SqlBuilder.select.table(ProjectColumn).where(
                ProjectColumn.column("project_id") == (project.id if isinstance(project, Project) else project)
            )
        ).all()
    return {column.get_uid(): (column.order, column.dock_order) for column in columns}


def test_replace_reorder_clear_and_replay(dock):
    repository, project, columns = dock
    first, second, third, archive, foreign = columns
    assert repository.replace_dock_columns(project, [third.get_uid(), first.get_uid()])
    assert snapshot(project) == {
        first.get_uid(): (0, 1),
        second.get_uid(): (1, None),
        third.get_uid(): (2, 0),
        archive.get_uid(): (3, None),
    }
    assert repository.replace_dock_columns(project, [first.get_uid()])
    before = snapshot(project)
    assert repository.replace_dock_columns(project, [first.get_uid()])
    assert snapshot(project) == before
    assert repository.replace_dock_columns(project, [])
    assert all(position is None for _, position in snapshot(project).values())
    assert snapshot(foreign.project_id)[foreign.get_uid()] == (0, None)


@pytest.mark.parametrize("target", ["duplicate", "foreign", "archive", "deleted", "missing"])
def test_invalid_replacement_preserves_entire_previous_dock(dock, target):
    repository, project, columns = dock
    first, second, third, archive, foreign = columns
    assert repository.replace_dock_columns(project, [first.get_uid()])
    if target == "deleted":
        with DbSession.use(readonly=False) as db:
            db.delete(third)
    before = snapshot(project)
    targets = {
        "duplicate": [second.get_uid(), second.get_uid()],
        "foreign": [second.get_uid(), foreign.get_uid()],
        "archive": [second.get_uid(), archive.get_uid()],
        "deleted": [second.get_uid(), third.get_uid()],
        "missing": [second.get_uid(), "absent"],
    }
    assert not repository.replace_dock_columns(project, targets[target])
    assert snapshot(project) == before


def test_failed_commit_rolls_back_bulk_replacement(dock, monkeypatch: pytest.MonkeyPatch):
    repository, project, columns = dock
    assert repository.replace_dock_columns(project, [columns[0].get_uid()])
    before = snapshot(project)
    original = DbSession.exec

    def fail_after_write(self, statement, **kwargs):
        result = original(self, statement, **kwargs)
        if statement.is_update:
            raise RuntimeError("test-only commit failure")
        return result

    with monkeypatch.context() as scope:
        scope.setattr(DbSession, "exec", fail_after_write)
        with pytest.raises(RuntimeError, match="test-only commit failure"):
            repository.replace_dock_columns(project, [columns[1].get_uid()])
    assert snapshot(project) == before


def test_absent_project_is_not_created(dock):
    repository, project, columns = dock
    before = snapshot(project)
    assert not repository.replace_dock_columns(project.id + 1, [])
    assert snapshot(project) == before


def test_dock_migration_preserves_existing_rows_on_upgrade_and_rollback():
    path = Path(__file__).resolve().parents[7] / "src/api/langboard/migrations/versions/20260915113000-6d4f2e8a9c10.py"
    spec = importlib.util.spec_from_file_location("dock_migration", path)
    assert spec and spec.loader
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    engine = create_engine("sqlite://")
    table = Table("project_column", MetaData(), Column("id", Integer, primary_key=True), Column("order", Integer))
    try:
        with engine.begin() as connection:
            table.create(connection)
            connection.execute(table.insert().values(id=1, order=7))
            migration.op = Operations(MigrationContext.configure(connection))
            migration.upgrade()
            upgraded = Table("project_column", MetaData(), autoload_with=connection)
            assert connection.execute(select(upgraded)).one()._mapping == {"id": 1, "order": 7, "dock_order": None}
            assert next(c for c in inspect(connection).get_columns("project_column") if c["name"] == "dock_order")[
                "nullable"
            ]
            connection.execute(upgraded.update().values(dock_order=0))
            migration.downgrade()
            assert connection.execute(select(table)).one()._mapping == {"id": 1, "order": 7}
            assert "dock_order" not in {c["name"] for c in inspect(connection).get_columns("project_column")}
            migration.upgrade()
            assert (
                connection.execute(select(Table("project_column", MetaData(), autoload_with=connection)))
                .one()
                ._mapping["dock_order"]
                is None
            )
    finally:
        engine.dispose()
