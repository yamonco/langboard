"""Real SQL projections hide prerequisite existence without opening execution gates."""

from dataclasses import replace
import pytest
from langboard_shared.core.db.DbEngine import DbEngine
from langboard_shared.domain.DependencyConditions import BLOCKING_RELATION_JOINS, UNSATISFIED_PREREQUISITE
from langboard_shared.domain.services.CardVisibilityPolicy import CardVisibilityContext, CollaborationChannel
from langboard_shared.domain.services.DependencyPolicy import dependency_blockers
from sqlalchemy import create_engine, text


@pytest.fixture
def dependency_db(monkeypatch):
    engine = create_engine("sqlite://")
    monkeypatch.setattr(DbEngine, "get_main_engine", lambda: engine)
    monkeypatch.setattr(DbEngine, "get_readonly_engine", lambda: engine)
    with engine.begin() as db:
        for sql in (
            "CREATE TABLE card(id integer PRIMARY KEY, project_id integer, project_column_id integer, deleted_at text, archived_at text, source_type text, title text, visibility text, owner_user_id integer)",
            "CREATE TABLE project_column(id integer PRIMARY KEY, project_id integer, deleted_at text, is_archive boolean, workflow_stage text)",
            "CREATE TABLE workflow_stage_definition(key text PRIMARY KEY, counts_as_completed boolean)",
            "CREATE TABLE global_card_relationship_type(id integer PRIMARY KEY, machine_semantic text)",
            "CREATE TABLE card_relationship(id integer PRIMARY KEY, card_id_parent integer, card_id_child integer, relationship_type_id integer)",
            "INSERT INTO project_column VALUES(1,1,NULL,false,'active')",
            "INSERT INTO workflow_stage_definition VALUES('active',false)",
            "INSERT INTO global_card_relationship_type VALUES(1,'blocks')",
            "INSERT INTO card VALUES(10,1,1,NULL,NULL,NULL,'Current','SHARED',NULL),(11,1,1,NULL,NULL,NULL,'Visible','SHARED',NULL),(12,1,1,NULL,NULL,NULL,'Hidden internal','INTERNAL',NULL),(13,1,1,NULL,NULL,NULL,'Own vault','PRIVATE',7),(14,1,1,NULL,NULL,NULL,'Other vault','PRIVATE',8),(15,1,1,NULL,NULL,NULL,'Own prerequisite','PRIVATE',7)",
            "INSERT INTO card_relationship VALUES(101,11,10,1),(102,12,10,1),(103,13,10,1),(104,14,10,1),(105,15,13,1),(106,14,13,1),(107,11,13,1)",
        ):
            db.execute(text(sql))
    yield engine
    engine.dispose()


@pytest.mark.parametrize("channel", list(CollaborationChannel))
@pytest.mark.parametrize("internal", [False, None, True])
def test_hidden_edges_never_contribute_identity_count_or_blocker_hint(dependency_db, channel, internal):
    context = CardVisibilityContext(channel, True, True, internal, actor_user_id=7)
    result = dependency_blockers([10,13], context=context)
    assert [row["title"] for row in result[10]] == (["Visible", "Hidden internal"] if internal is True else ["Visible"])
    assert [row["title"] for row in result[13]] == (["Own prerequisite"] if channel in (CollaborationChannel.HumanUI, CollaborationChannel.Mcp) else [])
    assert "Other vault" not in repr(result) and "Own vault" not in repr(result)
    for denied in (replace(context, active=False), replace(context, project_member=False)):
        assert dependency_blockers([10,13], context=denied) == {10: [],13: []}
    # Commit a change while keeping the same caller snapshot: primary reads win.
    with dependency_db.begin() as db:
        db.execute(text("UPDATE card SET visibility='INTERNAL' WHERE id=11"))
        db.execute(text("DELETE FROM card_relationship WHERE id=102"))
    external = replace(context, internal_member=False)
    assert dependency_blockers([10], context=external) == {10: []}
    # The execution condition still sees the hidden blockers; display cannot grant work.
    with dependency_db.connect() as db:
        sql = "SELECT count(*) FROM card c JOIN card_relationship r ON r.card_id_child=c.id " + BLOCKING_RELATION_JOINS + " WHERE c.id=10 AND " + UNSATISFIED_PREREQUISITE
        assert db.execute(text(sql)).scalar_one() == 3


def test_missing_audience_is_unknown_and_does_not_read_hidden_edges(dependency_db):
    assert dependency_blockers([10,13]) == {10: None,13: None}
    assert dependency_blockers([]) == {}
