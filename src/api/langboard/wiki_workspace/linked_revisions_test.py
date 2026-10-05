"""Current ACL checks and bounded-query linked wiki revisions."""

from types import SimpleNamespace
import pytest
from fastmcp.exceptions import AuthorizationError
from langboard_shared.core.db import DbSession, EditorContentModel
from langboard_shared.core.db.DbEngine import DbEngine
from langboard_shared.core.types import SafeDateTime
from langboard_shared.domain.models import ProjectWiki, ProjectWikiAssignedUser
from sqlalchemy import create_engine, delete, event, update
from .domain import WikiSnapshot
from .infrastructure import NativeWikiRepository


@pytest.fixture
def storage(monkeypatch):
    engine = create_engine("sqlite://")
    for model in (ProjectWiki, ProjectWikiAssignedUser):
        model.__table__.create(engine)
    monkeypatch.setattr(DbEngine, "get_main_engine", lambda: engine)
    monkeypatch.setattr(DbEngine, "get_readonly_engine", lambda: engine)
    service = SimpleNamespace(project=SimpleNamespace(get_by_id_like=lambda _: SimpleNamespace(id=1)))
    repository = NativeWikiRepository(SimpleNamespace(id=9, is_admin=False), service)
    with DbSession.use(readonly=False) as db:
        public = ProjectWiki(project_id=1, title="Public", content=EditorContentModel(content="one"))
        private = ProjectWiki(project_id=1, title="Private", is_public=False, content=EditorContentModel(content="two"))
        foreign = ProjectWiki(project_id=2, title="Foreign")
        deleted = ProjectWiki(project_id=1, title="Deleted", deleted_at=SafeDateTime.now())
        for wiki in (public, private, foreign, deleted):
            db.insert(wiki)
        assignment = ProjectWikiAssignedUser(project_assigned_id=7, project_wiki_id=private.id, user_id=9)
        db.insert(assignment)
    yield repository, engine, public, private, foreign, deleted, assignment
    engine.dispose()


def test_batch_reads_one_query_and_exact_revisions(storage):
    repository, engine, public, private, *_ = storage
    queries = []

    def capture(*args):
        queries.append(args[2])

    event.listen(engine, "before_cursor_execute", capture)
    try:
        revisions = repository.linked_revisions("project", [public.get_uid(), private.get_uid()])
    finally:
        event.remove(engine, "before_cursor_execute", capture)
    assert len(queries) == 1
    assert revisions == {
        wiki.get_uid(): WikiSnapshot(wiki.get_uid(), wiki.title, wiki.content.content).revision
        for wiki in (public, private)
    }
    with DbSession.use(readonly=False) as db:
        db.exec(
            update(ProjectWiki).where(ProjectWiki.id == public.id).values(content=EditorContentModel(content="changed"))
        )
    assert repository.linked_revisions("project", [public.get_uid()])[public.get_uid()] != revisions[public.get_uid()]


def test_revoked_assignment_does_not_reuse_observed_permission(storage):
    repository, _, _, private, _, _, assignment = storage
    assert repository.linked_revisions("project", [private.get_uid()])
    with DbSession.use(readonly=False) as db:
        db.exec(delete(ProjectWikiAssignedUser).where(ProjectWikiAssignedUser.id == assignment.id))
    with pytest.raises(AuthorizationError, match="purge cached"):
        repository.linked_revisions("project", [private.get_uid()])


@pytest.mark.parametrize("index", [4, 5])
def test_foreign_and_deleted_links_fail_closed(storage, index):
    with pytest.raises(AuthorizationError):
        storage[0].linked_revisions("project", [storage[index].get_uid()])


def test_admin_can_read_private_but_not_foreign(storage):
    repository, _, _, private, foreign, *_ = storage
    repository.user.is_admin = True
    assert repository.linked_revisions("project", [private.get_uid()])
    with pytest.raises(AuthorizationError):
        repository.linked_revisions("project", [foreign.get_uid()])


def test_empty_links_do_not_query(storage):
    repository = storage[0]
    repository.service.project.get_by_id_like = lambda _: pytest.fail("No lookup for empty links")
    assert repository.linked_revisions("project", []) == {}
