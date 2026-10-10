"""A display name never silently becomes a machine workflow state."""

import importlib.util
from pathlib import Path
import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations
from langboard.routes.board.forms import ColumnWorkflowStageForm


def test_column_stage_form_accepts_only_explicit_meanings() -> None:
    assert ColumnWorkflowStageForm(workflow_stage="review").workflow_stage == "review"
    assert ColumnWorkflowStageForm(workflow_stage=None).workflow_stage is None
    with pytest.raises(ValueError):
        ColumnWorkflowStageForm(workflow_stage="Done")


def test_migration_keeps_existing_column_names_and_starts_unclassified(monkeypatch: pytest.MonkeyPatch) -> None:
    path = (
        Path(__file__).resolve().parents[2]
        / "langboard/migrations/versions/20260929130500-80c532a4e7f1.py"
    )
    spec = importlib.util.spec_from_file_location("workflow_stage_migration", path)
    assert spec and spec.loader
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    engine = sa.create_engine("sqlite://")
    try:
        with engine.begin() as connection:
            connection.execute(sa.text("CREATE TABLE project_column (id INTEGER PRIMARY KEY, name TEXT NOT NULL)"))
            connection.execute(sa.text("INSERT INTO project_column VALUES (1, 'Done')"))
            monkeypatch.setattr(migration, "op", Operations(MigrationContext.configure(connection)))
            migration.upgrade()
            assert connection.execute(sa.text("SELECT name, workflow_stage FROM project_column")).one() == ("Done", None)
            connection.execute(sa.text("UPDATE project_column SET workflow_stage = 'review' WHERE id = 1"))
            assert connection.execute(sa.text("SELECT workflow_stage FROM project_column")).scalar_one() == "review"
            with pytest.raises(sa.exc.IntegrityError):
                connection.execute(sa.text("UPDATE project_column SET workflow_stage = 'Done' WHERE id = 1"))
            migration.downgrade()
            assert connection.execute(sa.text("SELECT name FROM project_column")).scalar_one() == "Done"
    finally:
        engine.dispose()
