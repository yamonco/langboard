"""Additive self-assignment persistence and concurrent replay proof."""

import os
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
import pytest
from sqlalchemy import create_engine
from ....core.db import DbSession
from ....core.db.DbEngine import DbEngine
from ....domain.models import Card, CardAssignedUser, Project, ProjectAssignedUser, ProjectColumn, User
from .CardAssignedUserRepository import CardAssignedUserRepository


def test_self_assignment_preserves_other_assignees_and_replay_is_noop(monkeypatch: pytest.MonkeyPatch) -> None:
    """Never replace existing assignees; serialize concurrent requests for the same member."""
    url = os.environ.get("LANGBOARD_WIKI_TEST_DATABASE_URL", "sqlite://")
    if url != "sqlite://":
        assert url.startswith("postgresql+psycopg://postgres@127.0.0.1:") and url.endswith("/langboard_wiki_test")
    engine = create_engine(url)
    try:
        for model in (User, Project, ProjectAssignedUser, ProjectColumn, Card, CardAssignedUser):
            model.__table__.create(engine, checkfirst=True)
        monkeypatch.setattr(DbEngine, "get_main_engine", lambda: engine)
        monkeypatch.setattr(DbEngine, "get_readonly_engine", lambda: engine)
        owner = User(firstname="Owner", lastname="Test", email="owner@example.invalid", password="test-only")
        actor = User(firstname="Actor", lastname="Test", email="actor@example.invalid", password="test-only")
        with DbSession.use(readonly=False) as db:
            db.insert(owner)
            db.insert(actor)
            project = Project(owner_id=owner.id, title="Isolated assignment test")
            db.insert(project)
            previous = ProjectAssignedUser(project_id=project.id, user_id=owner.id)
            member = ProjectAssignedUser(project_id=project.id, user_id=actor.id)
            db.insert(previous)
            db.insert(member)
            column = ProjectColumn(project_id=project.id, name="Todo")
            db.insert(column)
            card = Card(project_id=project.id, project_column_id=column.id, title="Test assignment")
            db.insert(card)
            db.insert(CardAssignedUser(card_id=card.id, project_assigned_id=previous.id, user_id=owner.id))
        repository = CardAssignedUserRepository(lambda _: None, lambda _: None)
        if engine.dialect.name == "postgresql":
            barrier = Barrier(2, timeout=10)

            def compete(_: int) -> bool:
                barrier.wait()
                return repository.add_member(card, member)

            with ThreadPoolExecutor(max_workers=2) as workers:
                results = list(workers.map(compete, [1, 2]))
            assert sorted(results) == [False, True]
        else:
            assert repository.add_member(card, member) is True
        assert repository.add_member(card, member) is False
        assigned = repository.get_all_by_card(card)
        assert {user.id for user, _ in assigned} == {owner.id, actor.id}
        assert len(assigned) == 2
        other_project = ProjectAssignedUser(project_id=project.id + 1, user_id=actor.id)
        with pytest.raises(ValueError, match="same project"):
            repository.add_member(card, other_project)
        assert len(repository.get_all_by_card(card)) == 2
    finally:
        engine.dispose()
