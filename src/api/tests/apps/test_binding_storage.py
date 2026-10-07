"""Actual migration storage preserves board/resource isolation and provenance."""

import importlib.util
import json
import os
from pathlib import Path
from uuid import uuid4
import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from langboard_shared.domain.models import AppConnection, AppResourceBinding, BoardAppBinding
from sqlalchemy import create_engine, inspect, text, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session


@pytest.fixture(params=["sqlite://", "postgresql-test"])
def storage(request):
    path = Path(__file__).parents[2] / "langboard/migrations/versions/20261008032000-719dab02cf46.py"
    spec = importlib.util.spec_from_file_location("app_storage_migration", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    database_url = request.param
    if database_url == "postgresql-test":
        database_url = os.environ.get("LANGBOARD_FILE_TEST_DATABASE_URL")
        if not database_url:
            pytest.skip("Set LANGBOARD_FILE_TEST_DATABASE_URL to a disposable PostgreSQL database")
    engine = create_engine(database_url)
    schema = None
    if engine.dialect.name == "postgresql":
        schema = "app_binding_test_" + uuid4().hex
        with engine.begin() as db:
            db.execute(text(f'CREATE SCHEMA "{schema}"'))
        engine.dispose()
        engine = create_engine(database_url, connect_args={"options": f"-csearch_path={schema}"})
    with engine.begin() as db:
        if engine.dialect.name == "sqlite":
            db.execute(text("PRAGMA foreign_keys=ON"))
        db.execute(text('CREATE TABLE "user" (id BIGINT PRIMARY KEY)'))
        db.execute(text("CREATE TABLE project (id BIGINT PRIMARY KEY)"))
        db.execute(text('INSERT INTO "user" VALUES (1)'))
        db.execute(text("INSERT INTO project VALUES (10),(11)"))
        with Operations.context(MigrationContext.configure(db)):
            migration.upgrade()
            for filename in ("20261008093000-b541ef460d80.py", "20261008095000-c652f0571e91.py"):
                spec = importlib.util.spec_from_file_location("app_lifecycle_migration", path.with_name(filename))
                followup = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(followup)
                followup.upgrade()
    with Session(engine, expire_on_commit=False) as db:
        connection = AppConnection(
            id=20, app_key="github", owner_id=1, state="connected", credential_reference="opaque-host-reference"
        )
        boards = [
            BoardAppBinding(id=30 + i, project_id=10 + i, app_key="github", workflow_mapping={"active": f"column-{i}"})
            for i in range(2)
        ]
        db.add(connection)
        db.add_all(boards)
        db.commit()
        resources = [
            AppResourceBinding(
                id=40 + i,
                board_binding_id=30 + (i // 2),
                connection_id=20,
                resource_type="repository",
                external_resource_id=str(i % 2),
                access_state="granted",
                health="healthy",
            )
            for i in range(4)
        ]
        db.add_all(resources)
        db.commit()
    try:
        yield engine, migration
    finally:
        if schema:
            with engine.begin() as db:
                db.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        engine.dispose()


def test_migration_and_orm_columns_and_constraints_agree(storage):
    engine, _ = storage
    inspector = inspect(engine)
    for model in (AppConnection, BoardAppBinding, AppResourceBinding):
        table = model.__table__
        assert {c["name"] for c in inspector.get_columns(table.name)} == set(table.columns.keys())
        assert {c["name"] for c in inspector.get_unique_constraints(table.name)} == {
            c.name for c in table.constraints if c.__class__.__name__ == "UniqueConstraint"
        }
        assert {c["name"] for c in inspector.get_check_constraints(table.name)} == {
            c.name for c in table.constraints if c.__class__.__name__ == "CheckConstraint"
        }
    assert AppConnection.model_construct(id=1, app_key="github", owner_id=1).state == "pending"
    assert not BoardAppBinding.model_construct(id=1, project_id=1, app_key="github").stage_transitions_enabled
    assert (
        AppResourceBinding.model_construct(
            id=1, board_binding_id=1, connection_id=1, resource_type="repository", external_resource_id="x"
        ).access_state
        == "unknown"
    )


def test_shared_connection_has_independent_board_mapping_and_resource_lifecycle(storage):
    engine, _ = storage
    with engine.begin() as db:
        db.execute(
            update(BoardAppBinding).where(BoardAppBinding.id == 30).values(workflow_mapping={"active": "new-column"})
        )
        db.execute(
            update(AppResourceBinding)
            .where(AppResourceBinding.id == 40)
            .values(access_state="revoked", health="unavailable", is_selected=False)
        )
    with engine.begin() as db:
        mapping = db.execute(text("SELECT workflow_mapping FROM board_app_binding WHERE id=31")).scalar_one()
        assert (json.loads(mapping) if isinstance(mapping, str) else mapping) == {"active": "column-1"}
        assert db.execute(text("SELECT health FROM app_resource_binding WHERE id=41")).scalar_one() == "healthy"
        assert db.execute(text("SELECT access_state FROM app_resource_binding WHERE id=42")).scalar_one() == "granted"
        db.execute(text("DELETE FROM app_resource_binding WHERE id=40"))
        assert db.execute(text("SELECT COUNT(*) FROM app_resource_binding WHERE id IN (41,42)")).scalar_one() == 2
        assert db.execute(text("SELECT state FROM app_connection WHERE id=20")).scalar_one() == "connected"


@pytest.mark.parametrize(
    "statement",
    [
        "UPDATE app_resource_binding SET health='invented' WHERE id=40",
        "UPDATE app_resource_binding SET access_state='invented' WHERE id=40",
        "UPDATE board_app_binding SET state='invented' WHERE id=30",
        "UPDATE app_connection SET state='invented' WHERE id=20",
        "UPDATE app_resource_binding SET connection_id=999 WHERE id=40",
        "UPDATE app_resource_binding SET external_resource_id='1' WHERE id=40",
        "UPDATE board_app_binding SET project_id=11 WHERE id=30",
        "DELETE FROM app_connection WHERE id=20",
        "DELETE FROM board_app_binding WHERE id=30",
    ],
)
def test_invalid_lifecycle_duplicates_and_dangling_rows_rejected(storage, statement):
    engine, _ = storage
    with engine.begin() as db:
        with pytest.raises(IntegrityError):
            db.execute(text(statement))


def test_downgrade_refuses_data_loss_then_removes_empty_tables(storage):
    engine, migration = storage
    with engine.begin() as db:
        with Operations.context(MigrationContext.configure(db)):
            with pytest.raises(RuntimeError, match="explicitly removed"):
                migration.downgrade()
            assert db.execute(text("SELECT COUNT(*) FROM app_resource_binding")).scalar_one() == 4
            for table in ("app_resource_binding", "board_app_binding", "app_connection"):
                db.execute(text(f"DELETE FROM {table}"))
            for filename in ("20261008095000-c652f0571e91.py", "20261008093000-b541ef460d80.py"):
                spec = importlib.util.spec_from_file_location(
                    "app_lifecycle_downgrade", Path(__file__).parents[2] / "langboard/migrations/versions" / filename
                )
                followup = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(followup)
                followup.downgrade()
            migration.downgrade()
        assert "app_connection" not in inspect(db).get_table_names()
