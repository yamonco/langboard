"""Execute wiki SQL projections and conditional writes against an isolated database."""

import os
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from types import SimpleNamespace
import pytest
from langboard_shared.core.db import DbSession, EditorContentModel
from langboard_shared.core.db.DbEngine import DbEngine
from langboard_shared.core.types import SafeDateTime
from langboard_shared.domain.models import (
    Bot,
    Project,
    ProjectAssignedUser,
    ProjectWiki,
    ProjectWikiActivity,
    ProjectWikiAssignedUser,
    User,
)
from langboard_shared.domain.models.ProjectWikiActivity import ProjectWikiActivityType
from langboard_shared.infrastructure.repositories.factory.ProjectWikiRepository import ProjectWikiRepository
from sqlalchemy import create_engine
from .infrastructure import NativeWikiRepository


def test_literal_search_filters_private_and_deleted_wikis_before_paging(monkeypatch: pytest.MonkeyPatch) -> None:
    """Wildcards remain literal; inaccessible/deleted content never consumes a page slot."""
    database_url = os.environ.get("LANGBOARD_WIKI_TEST_DATABASE_URL", "sqlite://")
    if database_url != "sqlite://":
        assert database_url.startswith("postgresql+psycopg://postgres@127.0.0.1:")
        assert database_url.endswith("/langboard_wiki_test")
    engine = create_engine(database_url)
    for model in (User, Bot, Project, ProjectAssignedUser, ProjectWiki, ProjectWikiAssignedUser, ProjectWikiActivity):
        model.__table__.create(engine, checkfirst=True)
    monkeypatch.setattr(DbEngine, "get_main_engine", lambda: engine)
    monkeypatch.setattr(DbEngine, "get_readonly_engine", lambda: engine)
    owner = User(firstname="Owner", lastname="Test", email="owner@example.invalid", password="test-only")
    user = User(firstname="Member", lastname="Test", email="member@example.invalid", password="test-only")
    with DbSession.use(readonly=False) as db:
        db.insert(owner)
        db.insert(user)
        project = Project(owner_id=owner.id, title="Isolated wiki test")
        db.insert(project)
        member = ProjectAssignedUser(project_id=project.id, user_id=user.id)
        db.insert(member)
    project_id, user_id = project.id, user.id
    records = [
        ProjectWiki(project_id=project_id, title=title, content=EditorContentModel(content=body), is_public=public)
        for title, body, public in (
            ("public", "주소: 100%_exact", True),
            ("private", "주소: 100%_exact SECRET", False),
            ("assigned", "주소: 100%_exact assigned", False),
            ("not literal", "주소: 100XXexact", True),
            ("deleted", "주소: 100%_exact removed", True),
        )
    ]
    records[-1].deleted_at = SafeDateTime.now()
    try:
        with DbSession.use(readonly=False) as db:
            for wiki in records:
                db.insert(wiki)
            db.insert(
                ProjectWikiAssignedUser(project_assigned_id=member.id, project_wiki_id=records[2].id, user_id=user_id)
            )
        service = SimpleNamespace(
            project=SimpleNamespace(get_by_id_like=lambda _: SimpleNamespace(id=project_id, owner_id=9))
        )
        repository = NativeWikiRepository(SimpleNamespace(id=user_id, is_admin=False), service)
        first = repository.list_wikis("project", "100%_exact", None, 1)
        second = repository.list_wikis("project", "100%_exact", first["next_cursor"], 1)
        expected_titles = [record.title for record in sorted((records[0], records[2]), key=lambda record: record.id)]
        assert [first["items"][0]["title"], second["items"][0]["title"]] == expected_titles
        assert second["next_cursor"] is None
        assert first["items"][0]["content_match"] is True
        assert "SECRET" not in str(first) + str(second)
        assert len(repository.list_wikis("project", "", None, 50)["items"]) == 3

        native = ProjectWikiRepository(lambda _: None, lambda _: None)
        original = records[0].content.content
        records[0].content = EditorContentModel(content=original + "\n\nAPPEND")
        assert native.update_content_if_current(records[0], original) is True
        records[0].content = EditorContentModel(content="STALE OVERWRITE")
        assert native.update_content_if_current(records[0], original) is False
        page = repository.list_wikis("project", "APPEND", None, 10)
        assert page["items"][0]["snippet"] == original + "\n\nAPPEND"
        activity = ProjectWikiActivity(
            user_id=user_id,
            bot_id=None,
            project_id=project_id,
            project_wiki_id=records[0].id,
            activity_type=ProjectWikiActivityType.WikiUpdated,
            activity_history={
                "changes": {
                    "before": {"content": {"content": original}},
                    "after": {"content": {"content": original + "\n\nAPPEND"}},
                }
            },
        )
        empty_activity = ProjectWikiActivity(
            user_id=user_id,
            bot_id=None,
            project_id=project_id,
            project_wiki_id=records[0].id,
            activity_type=ProjectWikiActivityType.WikiCreated,
            activity_history={},
        )
        with DbSession.use(readonly=False) as db:
            db.insert(activity)
            db.insert(empty_activity)
        service.project_wiki = SimpleNamespace(
            get_by_id_like=lambda _: records[0], convert_to_api_response=lambda *_: {"forbidden": False}
        )
        first_history = repository.revisions("project", records[0].get_uid(), None, 1)
        history = repository.revisions("project", records[0].get_uid(), first_history["next_cursor"], 1)
        assert {
            tuple(item["content_sides"])
            for page in (first_history, history)
            for item in page["items"]
        } == {(), ("before", "after")}
        assert history["next_cursor"] is None
        assert "activity_history" not in str(first_history) + str(history)
        old_page = repository.revision_page("project", records[0].get_uid(), activity.get_uid(), "before", None, 16000)
        assert old_page["content"] == original
        with pytest.raises(ValueError, match="no stored content snapshot"):
            repository.revision_page("project", records[0].get_uid(), empty_activity.get_uid(), "after", None, 100)
        if engine.dialect.name == "postgresql":
            barrier = Barrier(2, timeout=10)
            expected = original + "\n\nAPPEND"

            def compete(suffix: str) -> bool:
                candidate = ProjectWiki(
                    id=records[0].id,
                    project_id=project_id,
                    title="must not replace title",
                    content=EditorContentModel(content=expected + suffix),
                )
                barrier.wait()
                return native.update_content_if_current(candidate, expected)

            with ThreadPoolExecutor(max_workers=2) as workers:
                results = list(workers.map(compete, ["\nwriter A", "\nwriter B"]))
            assert sorted(results) == [False, True]
            saved = repository.list_wikis("project", "writer", None, 10)["items"]
            assert len(saved) == 1
            assert saved[0]["title"] == "public"
            assert saved[0]["snippet"] in [expected + "\nwriter A", expected + "\nwriter B"]
    finally:
        engine.dispose()
