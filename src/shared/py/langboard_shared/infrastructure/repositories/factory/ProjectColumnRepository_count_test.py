"""Column task counts exclude linked Wiki reference cards."""

import os


os.environ.setdefault("PROJECT_NAME", "langboard")

from sqlalchemy import create_engine
from ....core.db import DbSession
from ....core.db.DbEngine import DbEngine
from ....core.types import SafeDateTime
from ....domain.models import Card, Project, ProjectColumn, User
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
                Card(project_id=project.id, project_column_id=active.id, title="Task"),
                Card(
                    project_id=project.id,
                    project_column_id=active.id,
                    title="Wiki reference",
                    source_type=Card.LINKED_RESOURCE_PROJECT_WIKI,
                    source_uid="wiki-1",
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
    finally:
        engine.dispose()
