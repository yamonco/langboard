"""Exercise production SQL for the total accompanying project card pages."""

import os
from contextlib import contextmanager
from types import SimpleNamespace


os.environ.setdefault("PROJECT_NAME", "langboard")

from langboard_shared.core.db import DbSession  # noqa: E402
from langboard_shared.domain.models import Card, ProjectColumn  # noqa: E402
from langboard_shared.infrastructure.repositories.factory.CardRepository import CardRepository  # noqa: E402
from sqlalchemy import Column, Integer, MetaData, Table, create_engine  # noqa: E402


def test_page_total_excludes_deleted_cards_and_columns_but_keeps_archive(monkeypatch):
    engine = create_engine("sqlite://")
    metadata = MetaData()
    cards = Table(
        Card.__tablename__,
        metadata,
        Column("id", Integer, primary_key=True),
        Column("project_id", Integer),
        Column("project_column_id", Integer),
        Column("deleted_at", Integer),
        Column("archived_at", Integer),
    )
    columns = Table(
        ProjectColumn.__tablename__,
        metadata,
        Column("id", Integer, primary_key=True),
        Column("deleted_at", Integer),
    )
    metadata.create_all(engine)
    with engine.begin() as connection:
        connection.execute(columns.insert(), [{"id": 10, "deleted_at": None}, {"id": 20, "deleted_at": 1}])
        connection.execute(
            cards.insert(),
            [
                {
                    "id": uid,
                    "project_id": 1,
                    "project_column_id": 10,
                    "deleted_at": 1 if uid > 225 else None,
                    "archived_at": 1 if uid % 2 else None,
                }
                for uid in range(1, 248)
            ],
        )
        connection.execute(
            cards.insert(),
            [
                {"id": 248, "project_id": 2, "project_column_id": 20, "deleted_at": None, "archived_at": None},
                {"id": 249, "project_id": 2, "project_column_id": 10, "deleted_at": None, "archived_at": None},
            ],
        )

        @contextmanager
        def use(*, readonly):
            assert readonly
            yield SimpleNamespace(exec=lambda statement: connection.execute(statement).scalars())

        monkeypatch.setattr(DbSession, "use", use)
        repository = CardRepository(lambda _: None, lambda _: None)
        assert repository.count_by_project(1) == 225
        assert repository.count_by_project(2) == 1
        assert repository.count_by_project(99) == 0
