import importlib
from contextlib import contextmanager
from pathlib import Path
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations
from langboard_shared.infrastructure.repositories.factory.ProjectAssignedUserRepository import (  # noqa: E402
    ProjectAssignedUserRepository,
)
from langboard_shared.infrastructure.repositories.factory.ProjectRepository import ProjectRepository  # noqa: E402
from sqlalchemy.dialects import postgresql


ROOT = Path(__file__).resolve().parents[4]
VIEW_COUNT_MIGRATION = ROOT / "src/api/langboard/migrations/versions/20260911072500-57c4d82e1a63.py"


class _Result:
    def all(self):
        return []


class _Db:
    statement = None

    def exec(self, statement):
        self.statement = statement
        return _Result()


def test_project_list_orders_by_star_and_recorded_activity(monkeypatch) -> None:
    db = _Db()

    @contextmanager
    def use(*, readonly: bool):
        assert readonly is True
        yield db

    repository_module = importlib.import_module(ProjectRepository.__module__)
    monkeypatch.setattr(repository_module.DbSession, "use", use)

    ProjectRepository(lambda _: None, lambda _: None).get_all_by_user(7)

    sql = str(
        db.statement.compile(
            dialect=postgresql.dialect(),
            compile_kwargs={"literal_binds": True},
        )
    )
    assert "max(project_activity.created_at)" in sql
    assert "EXISTS (SELECT" in sql
    assert "card_assigned_user.user_id = 7" in sql
    assert "card_assigned_user.card_id = card.id" in sql
    assert "card.archived_at IS NULL" in sql
    assert "max(project_activity.created_at)" in sql
    assert "JOIN project_activity ON project_activity.card_id = card.id" in sql
    assert "related_activity_at" in sql
    assert "GROUP BY card.project_id" in sql
    assert "LEFT OUTER JOIN" in sql
    order_by = sql.split("ORDER BY", maxsplit=1)[1]
    assert "project_assigned_user.starred DESC" in order_by
    assert "project.updated_at" not in order_by


def test_view_tracking_updates_recency_and_frequency_together(monkeypatch) -> None:
    db = _Db()

    @contextmanager
    def use(*, readonly: bool):
        assert readonly is False
        yield db

    repository_module = importlib.import_module(ProjectAssignedUserRepository.__module__)
    monkeypatch.setattr(repository_module.DbSession, "use", use)

    ProjectAssignedUserRepository(lambda _: None, lambda _: None).set_last_view(7, 11)
    sql = str(db.statement.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}))
    assert "last_viewed_at=" in sql
    assert "view_count=(project_assigned_user.view_count + 1)" in sql


def test_view_count_migration_repairs_and_replays() -> None:
    spec = importlib.util.spec_from_file_location("project_view_count_migration", VIEW_COUNT_MIGRATION)
    assert spec and spec.loader
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)

    engine = sa.create_engine("sqlite://")
    with engine.begin() as connection:
        connection.execute(sa.text("CREATE TABLE project_assigned_user (id BIGINT PRIMARY KEY)"))
        migration.op = Operations(MigrationContext.configure(connection))

        migration.upgrade()
        migration.upgrade()
        columns = {column["name"] for column in sa.inspect(connection).get_columns("project_assigned_user")}
        assert "view_count" in columns

        migration.downgrade()
        migration.downgrade()
        columns = {column["name"] for column in sa.inspect(connection).get_columns("project_assigned_user")}
        assert "view_count" not in columns


def test_view_count_model_matches_the_database_default() -> None:
    """Core inserts that omit the counter retain the migration's zero default."""

    from langboard_shared.domain.models import ProjectAssignedUser

    assert ProjectAssignedUser.__table__.c.view_count.server_default is not None
    assert str(ProjectAssignedUser.__table__.c.view_count.server_default.arg) == "0"
