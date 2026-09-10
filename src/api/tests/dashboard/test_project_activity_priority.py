import importlib
from contextlib import contextmanager
from langboard_shared.infrastructure.repositories.factory.ProjectRepository import ProjectRepository  # noqa: E402
from sqlalchemy.dialects import postgresql


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
    assert "EXISTS (SELECT *" in sql
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
