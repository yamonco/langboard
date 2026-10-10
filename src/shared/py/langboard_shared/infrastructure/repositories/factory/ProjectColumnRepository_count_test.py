"""Column task counts exclude linked Wiki reference cards."""

import os


os.environ.setdefault("PROJECT_NAME", "langboard")

from sqlalchemy import create_engine
from ....core.db import DbSession, SqlBuilder
from ....core.db.DbEngine import DbEngine
from ....core.types import SafeDateTime
from ....domain.models import Card, Project, ProjectColumn, User
from .CardRepository import CardRepository
from .ProjectColumnRepository import ProjectColumnRepository


def test_column_count_excludes_linked_wiki_and_deleted_cards(monkeypatch):
    engine = create_engine("sqlite://")
    for model in (User, Project, ProjectColumn, Card):
        model.__table__.create(engine)
    monkeypatch.setattr(DbEngine, "get_main_engine", lambda: engine)
    monkeypatch.setattr(DbEngine, "get_readonly_engine", lambda: engine)
    try:
        with DbSession.use(readonly=False) as db:
            owner = User(firstname="Count", lastname="Test", email="count@example.invalid", password="test-only")
            db.insert(owner)
            project = Project(owner_id=owner.id, title="Count test")
            db.insert(project)
            active = ProjectColumn(project_id=project.id, name="Active", order=0)
            wiki_only = ProjectColumn(project_id=project.id, name="Wiki only", order=1)
            archive = ProjectColumn(project_id=project.id, name="Archive", order=2, is_archive=True)
            for column in (active, wiki_only, archive):
                db.insert(column)
            for card in (
                Card(project_id=project.id, project_column_id=active.id, title="Task", order=0),
                Card(
                    project_id=project.id,
                    project_column_id=active.id,
                    title="Wiki reference",
                    source_type=Card.LINKED_RESOURCE_PROJECT_WIKI,
                    source_uid="wiki-1",
                    order=1,
                ),
                Card(
                    project_id=project.id,
                    project_column_id=wiki_only.id,
                    title="Only wiki reference",
                    source_type=Card.LINKED_RESOURCE_PROJECT_WIKI,
                    source_uid="wiki-2",
                ),
                Card(
                    project_id=project.id, project_column_id=active.id, title="Deleted", deleted_at=SafeDateTime.now()
                ),
            ):
                db.insert(card)

        repository = ProjectColumnRepository(lambda _: None, lambda _: None)
        counts = {column.id: count for column, count in repository.get_all_by_project(project)}
        assert counts == {active.id: 1, wiki_only.id: 0, archive.id: 0}
        assert repository.count_cards(project, active) == 2
        assert repository.count_cards(project, active, exclude_linked_wikis=True) == 1
        assert repository.count_cards(project, wiki_only, exclude_linked_wikis=True) == 0

        with DbSession.use(readonly=False) as db:
            for order in range(3):
                db.insert(Card(project_id=project.id, project_column_id=archive.id, title=f"Archived {order}", order=order))
        CardRepository(lambda _: None, lambda _: None).move_all_by_column(active, archive, 2, is_archive=True)
        with DbSession.use(readonly=True) as db:
            cards = db.exec(SqlBuilder.select.table(Card).where(Card.column("project_column_id") == archive.id)).all()
            deleted = db.exec(SqlBuilder.select.table(Card, with_deleted=True).where(Card.column("title") == "Deleted")).first()
        assert sorted(card.order for card in cards) == [0, 1, 2, 3, 4]
        assert deleted.project_column_id == active.id and deleted.archived_at is None
        assert all(card.archived_at is not None for card in cards if card.title in {"Task", "Wiki reference"})
        counts = {column.id: count for column, count in repository.get_all_by_project(project)}
        assert counts == {active.id: 0, wiki_only.id: 0, archive.id: 4}
    finally:
        engine.dispose()
