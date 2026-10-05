"""Live SQL visibility filtering is constant-query and rechecks current grants."""

from types import SimpleNamespace
from unittest.mock import Mock
import pytest
from langboard.card_workspace.infrastructure.linked_wikis import visible_linked_wikis
from langboard_shared.core.db import DbSession
from langboard_shared.core.db.DbEngine import DbEngine
from langboard_shared.core.types import SafeDateTime
from langboard_shared.domain.models import Bot, ProjectWiki, ProjectWikiAssignedUser, User
from sqlalchemy import create_engine, delete, event


@pytest.fixture
def fixture(monkeypatch):
    engine = create_engine("sqlite://")
    for model in (ProjectWiki, ProjectWikiAssignedUser):
        model.__table__.create(engine)
    monkeypatch.setattr(DbEngine, "get_main_engine", lambda: engine)
    monkeypatch.setattr(DbEngine, "get_readonly_engine", lambda: pytest.fail("Current ACL must use primary"))
    actor = User(id=9, firstname="Member", lastname="Test", email="fixture@example.invalid", password="test-only")
    public = ProjectWiki(project_id=1, title="Public")
    private = ProjectWiki(project_id=1, title="Private", is_public=False)
    forbidden = ProjectWiki(project_id=1, title="Forbidden", is_public=False)
    foreign = ProjectWiki(project_id=2, title="Foreign")
    deleted = ProjectWiki(project_id=1, title="Deleted", deleted_at=SafeDateTime.now())
    wikis = [public, private, forbidden, foreign, deleted]
    with DbSession.use(readonly=False) as db:
        for wiki in wikis:
            db.insert(wiki)
        assignment = ProjectWikiAssignedUser(project_assigned_id=7, project_wiki_id=private.id, user_id=actor.id)
        db.insert(assignment)
    metadata = {"linked_wiki:" + wiki.get_uid(): "1" for wiki in wikis}
    metadata.update({"linked_wiki:invalid!": "1", "linked_wiki:disabled": "0"})
    service = SimpleNamespace(metadata=SimpleNamespace(get_all_as_api=Mock(return_value=metadata)))
    yield engine, actor, wikis, assignment, service
    engine.dispose()


def read(fixture, actor=None):
    return visible_linked_wikis(SimpleNamespace(id=1), object(), actor or fixture[1], fixture[4])


def test_one_query_filters_deleted_foreign_and_unassigned(fixture):
    engine, _, wikis, *_ = fixture
    statements = []

    def capture(*args):
        statements.append(args[2])

    event.listen(engine, "before_cursor_execute", capture)
    try:
        links = read(fixture)
    finally:
        event.remove(engine, "before_cursor_execute", capture)
    assert len(statements) == 1
    assert links == sorted(
        [{"wiki_uid": w.get_uid(), "title": w.title} for w in wikis[:2]], key=lambda x: x["wiki_uid"]
    )
    with DbSession.use(readonly=False) as db:
        db.exec(delete(ProjectWikiAssignedUser).where(ProjectWikiAssignedUser.id == fixture[3].id))
    assert read(fixture) == [{"wiki_uid": wikis[0].get_uid(), "title": "Public"}]


def test_bot_reads_only_public(fixture):
    bot = Bot.model_construct(name="Fixture", bot_uname="fixture")
    assert read(fixture, bot) == [{"wiki_uid": fixture[2][0].get_uid(), "title": "Public"}]


def test_admin_reads_private_but_no_foreign_or_deleted(fixture):
    fixture[1].is_admin = True
    assert {x["wiki_uid"] for x in read(fixture)} == {w.get_uid() for w in fixture[2][:3]}


def test_empty_metadata_never_queries(fixture):
    fixture[4].metadata.get_all_as_api.return_value = {}
    assert read(fixture) == []
