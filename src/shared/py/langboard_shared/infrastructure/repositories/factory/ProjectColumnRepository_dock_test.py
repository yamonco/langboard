"""Shared dock persistence preserves board order and rejects foreign targets."""

import importlib.util
import json
import os
import re
import subprocess
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from threading import Event, get_ident
from time import monotonic
from uuid import uuid4
import pytest
from alembic import command
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.script import ScriptDirectory
from sqlalchemy import Column, Integer, MetaData, Table, create_engine, event, inspect, select, text
from sqlalchemy.schema import CreateSchema, DropSchema
from ....core.db import BaseDbModel, DbSession, SqlBuilder
from ....core.db.DbEngine import DbEngine
from ....domain.models import Project, ProjectColumn, User
from ....domain.models.ProjectColumn import ProjectColumnDockConflict
from .ProjectColumnRepository import ProjectColumnRepository


@pytest.fixture
def dock(monkeypatch: pytest.MonkeyPatch, request: pytest.FixtureRequest):
    url = os.environ.get("LANGBOARD_DOCK_TEST_DATABASE_URL", "sqlite://")
    schema = None
    if url != "sqlite://":
        assert re.fullmatch(r"postgresql\+psycopg://postgres@127\.0\.0\.1:\d+/langboard_dock_test", url)
        schema = f"dock_test_{uuid4().hex}"
    admin = create_engine(url)
    engine = admin

    def cleanup():
        engine.dispose()
        try:
            if schema:
                with admin.begin() as connection:
                    connection.execute(DropSchema(schema, cascade=True))
        finally:
            admin.dispose()

    if schema:
        with admin.begin() as connection:
            connection.execute(CreateSchema(schema))
    request.addfinalizer(cleanup)
    if schema:
        engine = create_engine(url, connect_args={"options": f"-csearch_path={schema}"})
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
    yield ProjectColumnRepository(lambda _: None, lambda _: None), project, columns


def snapshot(project: Project | int):
    with DbSession.use(readonly=True) as db:
        columns = db.exec(
            SqlBuilder.select.table(ProjectColumn).where(
                ProjectColumn.column("project_id") == (project.id if isinstance(project, Project) else project)
            )
        ).all()
    return {column.get_uid(): (column.order, column.dock_order) for column in columns}


@pytest.mark.parametrize("operation", ["initial_save", "pinned_delete", "unpinned_delete"])
def test_postgresql_serializes_actual_concurrent_dock_commands(dock, operation):
    engine = DbEngine.get_main_engine()
    if engine.dialect.name != "postgresql":
        pytest.skip("Actual row-lock proof requires the isolated PostgreSQL test database")
    repository, project, columns = dock
    revision = 0
    if operation != "initial_save":
        revision = repository.replace_dock_columns(project, [columns[0].get_uid(), columns[2].get_uid()], 0)["revision"]
    acquired = Event()
    waiting = Event()
    release = Event()
    threads = {}
    backends = {}

    def before_lock(connection, cursor, statement, parameters, context, executemany):
        if "FOR UPDATE" in statement and get_ident() == threads.get("waiter"):
            backends["waiter"] = cursor.connection.info.backend_pid
            waiting.set()

    def after_lock(connection, cursor, statement, parameters, context, executemany):
        if "FOR UPDATE" in statement and get_ident() == threads.get("owner"):
            backends["owner"] = cursor.connection.info.backend_pid
            acquired.set()
            assert release.wait(10), "Test controller did not release the owned project lock"

    def owner_command():
        threads["owner"] = get_ident()
        if operation == "initial_save":
            return repository.replace_dock_columns(project.id, [columns[0].get_uid()], revision)
        target = columns[0] if operation == "pinned_delete" else columns[1]
        return repository.delete_with_dock_snapshot(project.id, target.id)

    def waiter_command():
        threads["waiter"] = get_ident()
        return repository.replace_dock_columns(project.id, [columns[2].get_uid()], revision)

    event.listen(engine, "before_cursor_execute", before_lock)
    event.listen(engine, "after_cursor_execute", after_lock)
    try:
        with ThreadPoolExecutor(max_workers=2) as workers:
            owner = workers.submit(owner_command)
            try:
                assert acquired.wait(5), "Owner never acquired the real PostgreSQL row lock"
                waiter = workers.submit(waiter_command)
                assert waiting.wait(5), "Waiter never attempted the real PostgreSQL row lock"
                assert backends["owner"] != backends["waiter"]
                deadline = monotonic() + 3
                blocked = False
                with engine.connect() as observer:
                    while monotonic() < deadline:
                        blockers = observer.execute(
                            text("SELECT pg_blocking_pids(:waiter)"), {"waiter": backends["waiter"]}
                        ).scalar_one()
                        if backends["owner"] in blockers:
                            blocked = True
                            break
                        release.wait(0.01)
                assert blocked, "PostgreSQL did not report the owner blocking the second command"
                assert not waiter.done()
            finally:
                release.set()
            committed = owner.result(timeout=5)
            if operation == "unpinned_delete":
                assert committed["revision"] == revision
                expected = waiter.result(timeout=5)
                assert expected == {"column_uids": [columns[2].get_uid()], "revision": revision + 1}
            else:
                with pytest.raises(ProjectColumnDockConflict):
                    waiter.result(timeout=5)
                expected = committed
                assert expected == {
                    "column_uids": [columns[0 if operation == "initial_save" else 2].get_uid()],
                    "revision": revision + 1,
                }
            assert repository.get_dock_snapshot(project.id) == expected
            values = snapshot(project.id)
            assert sorted(position[0] for position in values.values()) == list(range(len(values)))
            assert sorted(position[1] for position in values.values() if position[1] is not None) == list(
                range(len(expected["column_uids"]))
            )
    finally:
        release.set()
        event.remove(engine, "before_cursor_execute", before_lock)
        event.remove(engine, "after_cursor_execute", after_lock)


def test_read_snapshot_is_single_select_and_has_no_write_side_effect(dock):
    repository, project, columns = dock
    assert repository.get_dock_snapshot(project) == {"column_uids": [], "revision": 0}
    committed = repository.replace_dock_columns(project, [columns[2].get_uid(), columns[0].get_uid()], 0)
    before = snapshot(project)
    statements = []
    engine = DbEngine.get_main_engine()

    def observe(connection, cursor, statement, parameters, context, executemany):
        statements.append(statement)

    event.listen(engine, "before_cursor_execute", observe)
    try:
        assert repository.get_dock_snapshot(project) == committed
    finally:
        event.remove(engine, "before_cursor_execute", observe)
    assert len(statements) == 1
    assert statements[0].lstrip().upper().startswith("SELECT")
    assert snapshot(project) == before
    assert repository.get_dock_snapshot(project.id + 1000) is None


def test_read_snapshot_excludes_deleted_and_archive_slots(dock):
    repository, project, columns = dock
    committed = repository.replace_dock_columns(project, [columns[0].get_uid()], 0)
    with DbSession.use(readonly=False) as db:
        db.exec(
            SqlBuilder.update.table(ProjectColumn)
            .values(dock_order=2)
            .where(ProjectColumn.column("id") == columns[3].id)
        )
        db.exec(
            SqlBuilder.update.table(ProjectColumn)
            .values(deleted_at=columns[0].created_at)
            .where(ProjectColumn.column("id") == columns[0].id)
        )
    assert repository.get_dock_snapshot(project) == {"column_uids": [], "revision": committed["revision"]}


@pytest.mark.parametrize("index", [0, 1, 2])
def test_delete_pinned_column_compacts_dock_and_invalidates_old_writer(dock, index):
    repository, project, columns = dock
    ordered = [columns[2], columns[0], columns[1]]
    repository.replace_dock_columns(project, [item.get_uid() for item in ordered], 0)
    target = ordered[index]
    remaining = [item for item in ordered if item.id != target.id]
    result = repository.delete_with_dock_snapshot(project, target)
    assert result == {"column_uids": [item.get_uid() for item in remaining], "revision": 2}
    assert repository.get_dock_snapshot(project) == result
    values = snapshot(project)
    assert target.get_uid() not in values
    assert [values[item.get_uid()][1] for item in remaining] == [0, 1]
    for item in columns[:4]:
        if item.id != target.id:
            assert values[item.get_uid()][0] == item.order - int(item.order > target.order)
    with pytest.raises(ProjectColumnDockConflict):
        repository.replace_dock_columns(project, [], 1)
    assert repository.delete_with_dock_snapshot(project, target) is None
    assert repository.get_dock_snapshot(project) == result


def test_delete_unpinned_column_preserves_dock_revision(dock):
    repository, project, columns = dock
    expected = repository.replace_dock_columns(project, [columns[2].get_uid()], 0)
    assert repository.delete_with_dock_snapshot(project, columns[0]) == expected
    assert repository.get_dock_snapshot(project) == expected


def test_delete_last_shortcut_returns_empty_new_revision(dock):
    repository, project, columns = dock
    repository.replace_dock_columns(project, [columns[0].get_uid()], 0)
    expected = {"column_uids": [], "revision": 2}
    assert repository.delete_with_dock_snapshot(project, columns[0]) == expected
    assert repository.get_dock_snapshot(project) == expected


@pytest.mark.parametrize("index", [3, 4, None])
def test_delete_rejects_archive_foreign_and_missing_columns(dock, index):
    repository, project, columns = dock
    before = snapshot(project)
    target = columns[index] if index is not None else columns[0].id + 1000
    assert repository.delete_with_dock_snapshot(project, target) is None
    assert snapshot(project) == before


def test_delete_commit_failure_rolls_back_column_order_dock_and_revision(dock, monkeypatch):
    repository, project, columns = dock
    expected = repository.replace_dock_columns(project, [columns[2].get_uid(), columns[0].get_uid()], 0)
    before = snapshot(project)
    original = DbSession.exec
    writes = 0

    def fail_after_revision_write(self, query, *args, **kwargs):
        nonlocal writes
        result = original(self, query, *args, **kwargs)
        if str(query).lstrip().upper().startswith(("UPDATE", "DELETE")):
            writes += 1
            if writes == 4:
                raise RuntimeError("test-only delete commit failure")
        return result

    monkeypatch.setattr(DbSession, "exec", fail_after_revision_write)
    with pytest.raises(RuntimeError, match="test-only delete commit failure"):
        repository.delete_with_dock_snapshot(project, columns[0])
    assert writes == 4
    assert snapshot(project) == before
    assert repository.get_dock_snapshot(project) == expected


def test_replace_reorder_clear_and_replay(dock):
    repository, project, columns = dock
    first, second, third, archive, foreign = columns
    result = repository.replace_dock_columns(project, [third.get_uid(), first.get_uid()], 0)
    assert result["revision"] == 1
    assert snapshot(project) == {
        first.get_uid(): (0, 1),
        second.get_uid(): (1, None),
        third.get_uid(): (2, 0),
        archive.get_uid(): (3, None),
    }
    result = repository.replace_dock_columns(project, [first.get_uid()], 1)
    assert result["revision"] == 2
    before = snapshot(project)
    assert repository.replace_dock_columns(project, [first.get_uid()], 2) == result
    assert snapshot(project) == before
    assert repository.replace_dock_columns(project, [], 2)
    assert all(position is None for _, position in snapshot(project).values())
    assert snapshot(foreign.project_id)[foreign.get_uid()] == (0, None)


@pytest.mark.parametrize("target", ["duplicate", "foreign", "archive", "deleted", "missing"])
def test_invalid_replacement_preserves_entire_previous_dock(dock, target):
    repository, project, columns = dock
    first, second, third, archive, foreign = columns
    assert repository.replace_dock_columns(project, [first.get_uid()], 0)
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
    assert not repository.replace_dock_columns(project, targets[target], 1)
    assert snapshot(project) == before


def test_failed_commit_rolls_back_bulk_replacement(dock, monkeypatch: pytest.MonkeyPatch):
    repository, project, columns = dock
    assert repository.replace_dock_columns(project, [columns[0].get_uid()], 0)
    before = snapshot(project)
    original = DbSession.exec
    updates = 0

    def fail_after_write(self, statement, **kwargs):
        nonlocal updates
        result = original(self, statement, **kwargs)
        if statement.is_update:
            updates += 1
            if updates == 2:
                raise RuntimeError("test-only commit failure")
        return result

    with monkeypatch.context() as scope:
        scope.setattr(DbSession, "exec", fail_after_write)
        with pytest.raises(RuntimeError, match="test-only commit failure"):
            repository.replace_dock_columns(project, [columns[1].get_uid()], 1)
    assert snapshot(project) == before
    assert repository.replace_dock_columns(project, [columns[0].get_uid()], 1)["revision"] == 1


def test_absent_project_is_not_created(dock):
    repository, project, columns = dock
    before = snapshot(project)
    assert not repository.replace_dock_columns(project.id + 1, [], 0)
    assert snapshot(project) == before


@pytest.mark.parametrize("stale_targets", [[], [0], [1]])
def test_stale_writer_cannot_replace_or_clear_another_committed_configuration(dock, stale_targets, caplog):
    repository, project, columns = dock
    result = repository.replace_dock_columns(project, [columns[0].get_uid()], 0)
    before = snapshot(project)
    with pytest.raises(ProjectColumnDockConflict):
        repository.replace_dock_columns(project, [columns[i].get_uid() for i in stale_targets], 0)
    assert snapshot(project) == before
    assert not any(record.levelname == "ERROR" for record in caplog.records)
    assert repository.replace_dock_columns(project, [columns[0].get_uid()], 1) == result
    assert repository.replace_dock_columns(project, [columns[0].get_uid(), columns[1].get_uid()], 1)["revision"] == 2


def dock_migration(connection):
    path = Path(__file__).resolve().parents[7] / "src/api/langboard/migrations/versions/20260915113000-6d4f2e8a9c10.py"
    spec = importlib.util.spec_from_file_location("dock_migration", path)
    assert spec and spec.loader
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    migration.op = Operations(MigrationContext.configure(connection))
    return migration


def test_postgresql_full_migration_chain_replays_from_empty_owned_schema(dock):
    engine = DbEngine.get_main_engine()
    if engine.dialect.name != "postgresql":
        pytest.skip("Full PostgreSQL migration replay requires the isolated test database")
    root = Path(__file__).resolve().parents[7]
    config = Config()
    config.set_main_option("script_location", str(root / "src/api/langboard/migrations"))
    scripts = ScriptDirectory.from_config(config)
    revisions = list(reversed(list(scripts.iterate_revisions("heads", "base"))))
    assert scripts.get_heads() == ["6d4f2e8a9c10"]
    with engine.begin() as connection:
        for model in (ProjectColumn, Project, User):
            model.__table__.drop(connection)
        assert inspect(connection).get_table_names() == []
        config.attributes["connection"] = connection
        command.upgrade(config, "head")
        assert (
            connection.exec_driver_sql("SELECT version_num FROM alembic_version").scalars().all() == scripts.get_heads()
        )
        assert len(revisions) == 45
        tables = inspect(connection).get_table_names()
        for table in BaseDbModel.metadata.sorted_tables:
            assert table.name in tables, f"Missing migrated table: {table.name}"
            actual = {column["name"] for column in inspect(connection).get_columns(table.name)}
            missing = set(table.columns.keys()) - actual
            assert not missing, f"Missing migrated fields: {table.name}.{','.join(sorted(missing))}"
        for model in (User, Project, ProjectColumn):
            assert model.__tablename__ in tables
            actual = {column["name"] for column in inspect(connection).get_columns(model.__tablename__)}
            assert set(model.__table__.columns.keys()) <= actual
        assert connection.exec_driver_sql("SELECT count(*) FROM project").scalar_one() == 0
        assert connection.exec_driver_sql("SELECT count(*) FROM project_column").scalar_one() == 0
        command.downgrade(config, "404967cb79df")
        assert connection.exec_driver_sql("SELECT version_num FROM alembic_version").scalar_one() == "404967cb79df"
        assert "dock_order" not in {column["name"] for column in inspect(connection).get_columns("project_column")}
        command.upgrade(config, "head")
        command.upgrade(config, "head")
        assert connection.exec_driver_sql("SELECT version_num FROM alembic_version").scalar_one() == "6d4f2e8a9c10"


def test_postgresql_backup_restores_committed_dock_in_independent_database(dock, monkeypatch, tmp_path):
    engine = DbEngine.get_main_engine()
    if engine.dialect.name != "postgresql" or not os.environ.get("LANGBOARD_DOCK_TEST_PG_BINDIR"):
        pytest.skip("Restore proof requires the explicitly owned PostgreSQL runtime")
    binary = Path(os.environ["LANGBOARD_DOCK_TEST_PG_BINDIR"]).resolve()
    marker = json.loads((binary.parents[1] / "run.json").read_text())
    assert marker["purpose"] == "test"
    assert marker["run"] == "langboard-dock-postgresql-20260915"
    assert Path(marker["prefix"]).resolve() == binary.parent
    assert datetime.now(timezone.utc) < datetime.fromisoformat(marker["expires_at"].replace("Z", "+00:00"))
    assert engine.url.host == "127.0.0.1" and engine.url.database == marker["database"]
    repository, project, columns = dock
    expected = repository.replace_dock_columns(project, [columns[2].get_uid(), columns[0].get_uid()], 0)
    before = snapshot(project)
    with engine.connect() as connection:
        schema = connection.exec_driver_sql("SELECT current_schema()").scalar_one()
        assert re.fullmatch(r"dock_test_[0-9a-f]{32}", schema)
        original_rows = {
            model.__tablename__: [
                dict(row._mapping) for row in connection.execute(select(model.__table__).order_by(model.id))
            ]
            for model in (User, Project, ProjectColumn)
        }
    archive = tmp_path / "dock.dump"
    destination = f"dock_restore_{uuid4().hex}"
    common = ["-h", engine.url.host, "-p", str(engine.url.port), "-U", "postgres"]
    environment = {**os.environ, "PGPASSWORD": "", "PGOPTIONS": ""}

    def command(name, arguments):
        subprocess.run(
            [str(binary / name), *common, *arguments], env=environment, check=True, capture_output=True, timeout=20
        )

    command("pg_dump", ["-Fc", "--schema", schema, "-f", str(archive), marker["database"]])
    assert archive.stat().st_size > 0
    # Cleanup authority is earned only after this exact fresh database creation succeeds.
    command("createdb", ["-T", "template0", destination])
    restored = None
    try:
        command(
            "pg_restore",
            ["--exit-on-error", "--single-transaction", "--no-owner", "--no-acl", "-d", destination, str(archive)],
        )
        restored = create_engine(
            engine.url.set(database=destination), connect_args={"options": f"-csearch_path={schema}"}
        )
        with restored.connect() as connection:
            for model in (User, Project, ProjectColumn):
                rows = [dict(row._mapping) for row in connection.execute(select(model.__table__).order_by(model.id))]
                assert rows == original_rows[model.__tablename__]
        with monkeypatch.context() as scope:
            scope.setattr(DbEngine, "get_main_engine", lambda: restored)
            scope.setattr(DbEngine, "get_readonly_engine", lambda: restored)
            assert repository.get_dock_snapshot(project.id) == expected
            assert snapshot(project.id) == before
            with pytest.raises(ProjectColumnDockConflict):
                repository.replace_dock_columns(project.id, [], 0)
            assert repository.replace_dock_columns(project.id, [], expected["revision"]) == {
                "column_uids": [],
                "revision": expected["revision"] + 1,
            }
        assert repository.get_dock_snapshot(project.id) == expected
        assert snapshot(project.id) == before
    finally:
        if restored is not None:
            restored.dispose()
        command("dropdb", [destination])


def test_dock_migration_preserves_full_model_rows_keys_and_indexes(dock):
    engine = DbEngine.get_main_engine()

    def state(connection):
        result = {}
        for name in ("user", "project", "project_column"):
            table = Table(name, MetaData(), autoload_with=connection)
            fields = [column for column in table.columns if column.name not in ("dock_order", "dock_revision")]
            result[name] = {
                "rows": [dict(row._mapping) for row in connection.execute(select(*fields).order_by(table.c.id))],
                "primary_key": inspect(connection).get_pk_constraint(name),
                "foreign_keys": inspect(connection).get_foreign_keys(name),
                "indexes": inspect(connection).get_indexes(name),
            }
        return result

    with engine.begin() as connection:
        migration = dock_migration(connection)
        before = state(connection)
        # Derive the old shape from actual models, not a two-column surrogate.
        # This tests the Dock migration, not replay of the entire historical chain.
        migration.downgrade()
        assert state(connection) == before
        migration.upgrade()
        assert state(connection) == before
        project = Table("project", MetaData(), autoload_with=connection)
        columns = Table("project_column", MetaData(), autoload_with=connection)
        assert set(connection.execute(select(project.c.dock_revision)).scalars()) == {0}
        assert set(connection.execute(select(columns.c.dock_order)).scalars()) == {None}
        assert not next(c for c in inspect(connection).get_columns("project") if c["name"] == "dock_revision")[
            "nullable"
        ]
        assert next(c for c in inspect(connection).get_columns("project_column") if c["name"] == "dock_order")[
            "nullable"
        ]
        connection.execute(project.update().values(dock_revision=7))
        connection.execute(columns.update().values(dock_order=0))
        migration.downgrade()
        assert state(connection) == before
        for name, field in (("project", "dock_revision"), ("project_column", "dock_order")):
            assert field not in {column["name"] for column in inspect(connection).get_columns(name)}
        migration.upgrade()
        assert state(connection) == before
        assert set(connection.execute(select(project.c.dock_revision)).scalars()) == {0}
        assert set(connection.execute(select(columns.c.dock_order)).scalars()) == {None}


def test_postgresql_failed_dock_upgrade_rolls_back_first_ddl(dock):
    engine = DbEngine.get_main_engine()
    if engine.dialect.name != "postgresql":
        pytest.skip("Transactional DDL rollback requires isolated PostgreSQL")
    with engine.begin() as connection:
        dock_migration(connection).downgrade()

    def reject_second_ddl(connection, cursor, statement, parameters, context, executemany):
        if statement.lstrip().upper().startswith("ALTER TABLE project_column ADD COLUMN".upper()):
            raise RuntimeError("test-only second Dock DDL failure")

    event.listen(engine, "before_cursor_execute", reject_second_ddl)
    try:
        with pytest.raises(RuntimeError, match="test-only second Dock DDL failure"):
            with engine.begin() as connection:
                dock_migration(connection).upgrade()
    finally:
        event.remove(engine, "before_cursor_execute", reject_second_ddl)
    with engine.begin() as connection:
        for name, field in (("project", "dock_revision"), ("project_column", "dock_order")):
            assert field not in {column["name"] for column in inspect(connection).get_columns(name)}
        dock_migration(connection).upgrade()
    assert dock[0].get_dock_snapshot(dock[1]) == {"column_uids": [], "revision": 0}


def test_dock_migration_preserves_existing_rows_on_upgrade_and_rollback():
    engine = create_engine("sqlite://")
    table = Table("project_column", MetaData(), Column("id", Integer, primary_key=True), Column("order", Integer))
    try:
        with engine.begin() as connection:
            project_table = Table("project", MetaData(), Column("id", Integer, primary_key=True))
            project_table.create(connection)
            connection.execute(project_table.insert().values(id=1))
            table.create(connection)
            connection.execute(table.insert().values(id=1, order=7))
            migration = dock_migration(connection)
            migration.upgrade()
            upgraded_project = Table("project", MetaData(), autoload_with=connection)
            assert connection.execute(select(upgraded_project)).one()._mapping["dock_revision"] == 0
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
