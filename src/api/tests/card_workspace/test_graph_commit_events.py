"""Graph effects wait for the owning transaction to commit."""

import importlib
from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import Mock
import pytest
from langboard_shared.core.db import DbSession
from langboard_shared.core.db.DbEngine import DbEngine
from langboard_shared.core.types import SnowflakeID
from langboard_shared.domain.models import Card, Project, ProjectColumn
from langboard_shared.domain.services.factory.CardRelationshipService import CardRelationshipService
from langboard_shared.helpers import InfraHelper
from langboard_shared.publishers import CardRelationshipPublisher
from langboard_shared.tasks.bots import CardBotTask
from sqlalchemy import create_engine, text


@pytest.mark.parametrize("mode", ["commit", "repository_failure", "outer_rollback", "silent"])
def test_graph_events_follow_outer_commit(monkeypatch, mode):
    module = importlib.import_module(CardRelationshipService.__module__)
    engine = create_engine("sqlite://")
    with engine.begin() as c:
        c.execute(text(f'CREATE TABLE "{Project.__tablename__}" (id INTEGER PRIMARY KEY)'))
        c.execute(text(f'INSERT INTO "{Project.__tablename__}" VALUES (1)'))
        c.execute(text("CREATE TABLE edges (id INTEGER)"))
        c.execute(text("INSERT INTO edges VALUES (10)"))
    monkeypatch.setattr(DbEngine, "get_main_engine", lambda: engine)
    monkeypatch.setattr(DbEngine, "get_readonly_engine", lambda: engine)
    project = Project(id=1, owner_id=1, title="Board")
    column = ProjectColumn(id=3, project_id=1, name="Backlog", order=0)
    anchor = Card(id=1, project_id=1, project_column_id=3, title="Anchor", order=0)
    child = Card(id=2, project_id=1, project_column_id=3, title="Child", order=1)
    monkeypatch.setattr(InfraHelper, "get_records_with_foreign_by_params", lambda *_: (project, anchor))
    monkeypatch.setattr(InfraHelper, "get_by_id_like", lambda cls, uid: column if cls is ProjectColumn else anchor if uid == anchor.get_uid() else child)

    @contextmanager
    def readiness():
        yield SimpleNamespace(watch=lambda *_: None, watch_new=lambda *_: None)

    monkeypatch.setattr(module, "execution_readiness_uow", readiness)
    published, bot, states = Mock(), Mock(), Mock()
    monkeypatch.setattr(CardRelationshipPublisher, "updated", published)
    monkeypatch.setattr(CardBotTask, "card_relationship_updated", bot)

    def persist(*_):
        with DbSession.use(readonly=False) as db:
            db.exec(text("DELETE FROM edges"))
        if mode == "repository_failure":
            raise RuntimeError("Graph save failed")
        return []

    service = CardRelationshipService(
        lambda _: SimpleNamespace(publish_work_states=states), lambda _: None,
        SimpleNamespace(card_relationship=SimpleNamespace(
            get_graph_snapshot=lambda _: [(10, 1, 2, 20)],
            get_global_relationship_types_map=lambda _: {},
            apply_graph_patch=persist,
        )),
    )
    monkeypatch.setattr(service, "get_api_list_by_card", lambda _: [])

    def apply():
        with DbSession.atomic():
            result = service.apply_graph_patch(
                None, project, anchor, [], [], [SnowflakeID(10).to_short_code()],
                dispatch_effects=mode != "silent",
            )
            assert result and not published.called and not bot.called and not states.called
            if mode == "outer_rollback":
                raise RuntimeError("Plan failed")

    if mode in {"repository_failure", "outer_rollback"}:
        with pytest.raises(RuntimeError):
            apply()
    else:
        apply()
    with engine.connect() as c:
        assert c.execute(text("SELECT count(*) FROM edges")).scalar() == int(mode in {"repository_failure", "outer_rollback"})
    assert published.call_count == bot.call_count == (2 if mode == "commit" else 0)
    assert states.call_count == int(mode == "commit")
    engine.dispose()
