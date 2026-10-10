"""Registry foreign key migration preserves bindings and rejects destructive rollback."""

import importlib.util
from pathlib import Path
import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from langboard.routes.board.forms.Column import ColumnWorkflowStageForm
from sqlalchemy import create_engine, text
from sqlalchemy.exc import IntegrityError


def test_registry_binding_migration_preserves_null_and_builtin_and_accepts_custom():
    path = Path(__file__).parents[2] / "langboard/migrations/versions/20261002234000-7be934f2a6c1.py"
    spec = importlib.util.spec_from_file_location("binding_migration", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    engine = create_engine("sqlite://")
    with engine.connect() as connection:
        connection.execute(text("PRAGMA foreign_keys=ON"))
        connection.execute(text("CREATE TABLE workflow_stage_definition(key TEXT PRIMARY KEY)"))
        connection.execute(text("INSERT INTO workflow_stage_definition VALUES ('closed'),('released')"))
        connection.execute(
            text(
                "CREATE TABLE project_column(id INTEGER PRIMARY KEY, workflow_stage TEXT, CONSTRAINT ck_project_column_workflow_stage CHECK(workflow_stage IS NULL OR workflow_stage IN ('backlog','ready','active','review','closed','reference')))"
            )
        )
        connection.execute(text("INSERT INTO project_column VALUES (1,'closed'),(2,NULL)"))
        with Operations.context(MigrationContext.configure(connection)):
            module.upgrade()
        assert connection.execute(text("SELECT workflow_stage FROM project_column ORDER BY id")).scalars().all() == [
            "closed",
            None,
        ]
        connection.execute(text("UPDATE project_column SET workflow_stage='released' WHERE id=2"))
        with pytest.raises(IntegrityError):
            connection.execute(text("UPDATE project_column SET workflow_stage='missing' WHERE id=2"))
        with Operations.context(MigrationContext.configure(connection)):
            with pytest.raises(RuntimeError, match="explicitly migrated"):
                module.downgrade()
        assert (
            connection.execute(text("SELECT workflow_stage FROM project_column WHERE id=2")).scalar_one() == "released"
        )
        connection.execute(text("UPDATE project_column SET workflow_stage=NULL WHERE id=2"))
        with Operations.context(MigrationContext.configure(connection)):
            module.downgrade()
        with pytest.raises(IntegrityError):
            connection.execute(text("UPDATE project_column SET workflow_stage='released' WHERE id=2"))
    engine.dispose()


def test_column_form_accepts_registry_key_and_null_without_fixed_enum():
    assert ColumnWorkflowStageForm(workflow_stage="released").workflow_stage == "released"
    assert ColumnWorkflowStageForm(workflow_stage=None).workflow_stage is None
    with pytest.raises(ValueError):
        ColumnWorkflowStageForm(workflow_stage="Bad key")
