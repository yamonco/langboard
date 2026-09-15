"""Bounded literal search across card text, comments and attachment names."""

from datetime import timedelta
import pytest
from sqlalchemy import create_engine, update
from sqlalchemy.dialects import postgresql
from ....core.db import DbSession, EditorContentModel
from ....core.db.DbEngine import DbEngine
from ....core.storage import FileModel
from ....core.types import SafeDateTime
from ....domain.models import Card, CardAttachment, CardComment, Project, ProjectColumn, User
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
