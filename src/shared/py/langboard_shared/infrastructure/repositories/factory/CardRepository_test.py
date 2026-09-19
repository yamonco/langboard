"""Bounded literal search across card text, comments and attachment names."""

import os


os.environ.setdefault("PROJECT_NAME", "langboard")

from datetime import timedelta
import pytest
from sqlalchemy import create_engine, update
from sqlalchemy.dialects import postgresql
from ....core.db import DbSession, EditorContentModel
from ....core.db.DbEngine import DbEngine
from ....core.storage import FileModel
from ....core.types import SafeDateTime
from ....domain.models import (
    Bot,
    Card,
    CardAssignedUser,
    CardAttachment,
    CardComment,
    Project,
    ProjectAssignedUser,
    ProjectColumn,
    User,
    UserNotification,
)
from ....domain.models.BaseBotModel import BotPlatform, BotPlatformRunningType
from ....domain.models.UserNotification import NotificationType
from .CardRepository import CardRepository, _editor_search_text


def test_search_matches_comment_only_unicode_and_deduplicates_without_cross_project_leaks(monkeypatch):
    engine = create_engine("sqlite://")
    for model in (User, Project, ProjectColumn, Card, CardComment, CardAttachment):
        model.__table__.create(engine)
    monkeypatch.setattr(DbEngine, "get_main_engine", lambda: engine)
    monkeypatch.setattr(DbEngine, "get_readonly_engine", lambda: engine)
    try:
        with DbSession.use(readonly=False) as db:
            owner = User(firstname="Test", lastname="Owner", email="search@example.invalid", password="test-only")
            db.insert(owner)
            project = Project(owner_id=owner.id, title="Owned search fixture")
            other = Project(owner_id=owner.id, title="Other project")
            db.insert(project)
            db.insert(other)
            column = ProjectColumn(project_id=project.id, name="Todo")
            db.insert(column)
            cards = [
                Card(project_id=p.id, project_column_id=column.id, title=t)
                for p, t in [
                    (project, "Comment only"),
                    (project, "Deleted comment"),
                    (other, "Foreign card"),
                    (project, "Body only"),
                    (project, "Literal 100%_done"),
                ]
            ]
            for card in cards:
                db.insert(card)
            for card in cards[:3]:
                db.insert(
                    CardComment(
                        card_id=card.id,
                        user_id=owner.id,
                        content=EditorContentModel(content="기쁨 @mention"),
                        deleted_at=SafeDateTime.now() if card == cards[1] else None,
                    )
                )
            db.insert(
                CardComment(
                    card_id=cards[0].id, user_id=owner.id, content=EditorContentModel(content="기쁨 두 번째 댓글")
                )
            )
            cards[3].description = EditorContentModel(content="본문 전용 식별자")
            db.update(cards[3])
            file = FileModel(
                storage_type="test",
                storage_name="test",
                original_filename="회의자료.png",
                filename="fixture.png",
                path="/test/fixture.png",
            )
            db.insert(CardAttachment(card_id=cards[0].id, user_id=owner.id, filename="회의자료.png", file=file))
            db.insert(
                CardAttachment(
                    card_id=cards[1].id,
                    user_id=owner.id,
                    filename="삭제자료.png",
                    file=file,
                    deleted_at=SafeDateTime.now(),
                )
            )
        repository = CardRepository(lambda _: None, lambda _: None)
        assert [c.title for c, _ in repository.search_context_by_project(project, "기쁨")] == ["Comment only"]
        assert [c.title for c, _ in repository.search_context_by_project(project, "본문 전용")] == ["Body only"]
        assert [c.title for c, _ in repository.search_context_by_project(project, "100%_done")] == ["Literal 100%_done"]
        assert repository.search_context_by_project(project, "missing") == []
        assert [c.title for c, _ in repository.search_context_by_project(project, "회의자료")] == ["Comment only"]
        assert repository.search_context_by_project(project, "삭제자료") == []
        assert len(repository.search_context_by_project(project, "only", limit=1)) == 1
        start = SafeDateTime(2026, 9, 1)
        with DbSession.use(readonly=False) as db:
            for index, card in enumerate(cards):
                db.exec(
                    update(Card.__table__)
                    .where(Card.column("id") == card.id)
                    .values(
                        created_at=start + timedelta(days=index),
                        updated_at=start + timedelta(days=index + 10),
                    )
                )
        assert [
            c.title
            for c, _ in repository.search_context_by_project(
                project,
                "",
                date_field="created_at",
                since=start,
                until=start + timedelta(days=1),
            )
        ] == ["Comment only"]
        assert [
            c.title
            for c, _ in repository.search_context_by_project(
                project,
                "",
                date_field="created_at",
                since=start + timedelta(days=1),
                until=start + timedelta(days=2),
            )
        ] == ["Deleted comment"]
        assert [
            c.title
            for c, _ in repository.search_context_by_project(
                project,
                "",
                date_field="updated_at",
                since=start + timedelta(days=10),
                until=start + timedelta(days=11),
            )
        ] == ["Comment only"]
        with pytest.raises(ValueError, match="date_field"):
            repository.search_context_by_project(project, "", date_field="deadline_at")
        with pytest.raises(ValueError, match="earlier"):
            repository.search_context_by_project(project, "", since=start, until=start)
        expression = _editor_search_text(CardComment.column("content"), "postgresql")
        compiled = str(expression.compile(dialect=postgresql.dialect()))
        assert "#>>" in compiled and "TEXT[]" in compiled
        with pytest.raises(ValueError, match="Unsupported"):
            _editor_search_text(CardComment.column("content"), "unknown")
    finally:
        engine.dispose()


def test_my_work_page_deduplicates_user_relationships_across_projects(monkeypatch):
    """Assigned, created and mentioned cards collapse into one bounded queue."""

    engine = create_engine("sqlite://")
    for model in (
        User,
        Project,
        ProjectColumn,
        Card,
        CardAssignedUser,
        ProjectAssignedUser,
        UserNotification,
    ):
        model.__table__.create(engine)
    monkeypatch.setattr(DbEngine, "get_main_engine", lambda: engine)
    monkeypatch.setattr(DbEngine, "get_readonly_engine", lambda: engine)
    try:
        with DbSession.use(readonly=False) as db:
            worker = User(firstname="Work", lastname="Worker", email="work@example.invalid", password="test-only")
            owner = User(firstname="Board", lastname="Owner", email="owner@example.invalid", password="test-only")
            db.insert(worker)
            db.insert(owner)
            projects = [Project(owner_id=owner.id, title=f"My Work {index}") for index in range(2)]
            for project in projects:
                db.insert(project)
            assignment = ProjectAssignedUser(project_id=projects[0].id, user_id=worker.id)
            db.insert(assignment)
            columns = [ProjectColumn(project_id=project.id, name="Doing") for project in projects]
            for column in columns:
                db.insert(column)
            assigned = Card(project_id=projects[0].id, project_column_id=columns[0].id, title="Assigned")
            mentioned = Card(project_id=projects[1].id, project_column_id=columns[1].id, title="Mentioned")
            foreign = Card(project_id=projects[1].id, project_column_id=columns[1].id, title="Foreign")
            for card in (assigned, mentioned, foreign):
                db.insert(card)
            db.insert(CardAssignedUser(project_assigned_id=assignment.id, card_id=assigned.id, user_id=worker.id))
            db.insert(
                UserNotification(
                    notifier_type="user",
                    notifier_id=owner.id,
                    receiver_id=worker.id,
                    notification_type=NotificationType.MentionedInComment,
                    record_list=[("card", mentioned.id)],
                    read_at=SafeDateTime.now(),
                )
            )
            db.insert(
                UserNotification(
                    notifier_type="user",
                    notifier_id=owner.id,
                    receiver_id=owner.id,
                    notification_type=NotificationType.MentionedInComment,
                    record_list=[("card", foreign.id)],
                )
            )
        repository = CardRepository(lambda _: None, lambda _: None)
        now = SafeDateTime.now()
        records = repository.get_my_work_page(
            worker,
            [project.get_uid() for project in projects],
            {"assigned", "mentioned", "due_soon", "overdue", "created"},
            [mentioned.id],
            now,
            now + timedelta(days=7),
            "updated_at",
            None,
            None,
            10,
        )
        assert sorted((card.title, is_assigned) for card, _, _, is_assigned in records) == [
            ("Assigned", True),
            ("Mentioned", False),
        ]
    finally:
        engine.dispose()


def test_board_creators_resolve_visible_user_and_bot_authors_without_hiding_recent_archives(monkeypatch):
    """Keep visible recent archive authors while excluding hidden old archive cards."""
    engine = create_engine("sqlite://")
    for model in (User, Bot, Project, ProjectColumn, Card):
        model.__table__.create(engine)
    monkeypatch.setattr(DbEngine, "get_main_engine", lambda: engine)
    monkeypatch.setattr(DbEngine, "get_readonly_engine", lambda: engine)
    try:
        archive_visible_since = SafeDateTime(2026, 9, 10)
        with DbSession.use(readonly=False) as db:
            author = User(firstname="Card", lastname="Author", email="creator@example.invalid", password="test-only")
            bot = Bot(
                name="Integration",
                bot_uname="integration",
                platform=BotPlatform.Default,
                platform_running_type=BotPlatformRunningType.Default,
                app_api_token="test-only",
            )
            db.insert(author)
            db.insert(bot)
            project = Project(owner_id=author.id, title="Creator projection fixture")
            db.insert(project)
            column = ProjectColumn(project_id=project.id, name="Todo")
            db.insert(column)
            cards = {
                "active": Card(
                    project_id=project.id,
                    project_column_id=column.id,
                    title="Active",
                    created_by_user_id=author.id,
                ),
                "bot": Card(
                    project_id=project.id,
                    project_column_id=column.id,
                    title="Bot created",
                    created_by_bot_id=bot.id,
                ),
                "recent_archive": Card(
                    project_id=project.id,
                    project_column_id=column.id,
                    title="Recent archive",
                    created_by_user_id=author.id,
                    archived_at=archive_visible_since + timedelta(days=1),
                ),
                "old_archive": Card(
                    project_id=project.id,
                    project_column_id=column.id,
                    title="Old archive",
                    created_by_user_id=author.id,
                    archived_at=archive_visible_since - timedelta(days=1),
                ),
            }
            for card in cards.values():
                db.insert(card)
        repository = CardRepository(lambda _: None, lambda _: None)
        creators = repository.get_board_creators(project, archive_visible_since)

        assert set(creators) == {cards["active"].id, cards["bot"].id, cards["recent_archive"].id}
        assert creators[cards["active"].id].id == author.id
        assert creators[cards["recent_archive"].id].id == author.id
        assert creators[cards["bot"].id].id == bot.id
        assert cards["old_archive"].id not in creators
    finally:
        engine.dispose()
