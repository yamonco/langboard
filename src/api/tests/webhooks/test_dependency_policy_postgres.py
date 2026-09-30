"""PostgreSQL proof that public blockers and execution fences share one policy."""

import os
from uuid import uuid4
import pytest
from sqlalchemy import create_engine, text


os.environ.setdefault("PROJECT_NAME", "langboard")
from langboard_shared.core.db.DbEngine import DbEngine  # noqa: E402
from langboard_shared.domain.services.DependencyPolicy import dependency_blockers  # noqa: E402
from langboard_shared.tasks.webhooks.ExecutionReadinessUow import _READY_EXPRESSION  # noqa: E402


DATABASE_URL = os.getenv("LANGBOARD_OUTBOX_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not DATABASE_URL, reason="dedicated PostgreSQL policy proof")


@pytest.fixture
def policy_db(monkeypatch):
    schema = f"dependency_policy_{uuid4().hex}"
    admin = create_engine(DATABASE_URL)
    with admin.begin() as conn:
        conn.execute(text(f"CREATE SCHEMA {schema}"))
    engine = create_engine(DATABASE_URL, connect_args={"options": f"-csearch_path={schema}"})
    monkeypatch.setattr(DbEngine, "get_main_engine", lambda: engine)
    monkeypatch.setattr(DbEngine, "get_readonly_engine", lambda: engine)
    try:
        with engine.begin() as conn:
            for sql in (
                "CREATE TABLE project_column(id bigint PRIMARY KEY, project_id bigint, deleted_at timestamptz, is_archive boolean, workflow_stage text)",
                "CREATE TABLE card(id bigint PRIMARY KEY, project_id bigint, project_column_id bigint, deleted_at timestamptz, archived_at timestamptz, source_type text, title text)",
                "CREATE TABLE global_card_relationship_type(id bigint PRIMARY KEY, machine_semantic text, is_active boolean)",
                "CREATE TABLE card_relationship(id bigint PRIMARY KEY, card_id_parent bigint, card_id_child bigint, relationship_type_id bigint)",
                "CREATE TABLE project_execution_binding(project_id bigint, is_enabled boolean, prerequisite_relationship_type_id bigint, events jsonb, webhook_id bigint, column_semantic_ids jsonb)",
                "CREATE TABLE webhook_setting(id bigint PRIMARY KEY, secret_id bigint, events jsonb)",
                "INSERT INTO project_column VALUES(10,1,NULL,false,'ready'),(11,1,NULL,false,'active'),(12,1,NULL,false,'closed'),(13,9,NULL,false,'closed')",
                "INSERT INTO card VALUES(20,1,10,NULL,NULL,NULL,'Current'),(21,1,11,NULL,NULL,NULL,'Open'),(22,1,12,NULL,NULL,NULL,'Closed'),(23,9,13,NULL,NULL,NULL,'PRIVATE_FOREIGN_TITLE'),(24,1,11,NULL,NULL,'wiki','PRIVATE_LINKED_TITLE')",
                "INSERT INTO global_card_relationship_type VALUES(1,'blocks',true),(2,'contains',true),(3,'references',true),(4,NULL,false),(5,'blocks',true)",
                "INSERT INTO webhook_setting VALUES(1,1,'[\"io.langboard.work.ready.v1\"]')",
                'INSERT INTO project_execution_binding VALUES(1,true,1,\'["io.langboard.work.ready.v1"]\',1,\'{"10":"ready","12":"terminal"}\')',
            ):
                conn.execute(text(sql))
        yield engine
    finally:
        engine.dispose()
        with admin.begin() as conn:
            conn.execute(text(f"DROP SCHEMA {schema} CASCADE"))
        admin.dispose()


def ready(engine):
    with engine.connect() as conn:
        return conn.execute(text("SELECT " + _READY_EXPRESSION), {"card_id": 20}).scalar_one()


def edge(engine, parent, type_id, edge_id=1):
    with engine.begin() as conn:
        conn.execute(
            text("INSERT INTO card_relationship VALUES(:id,:parent,20,:type)"),
            {"id": edge_id, "parent": parent, "type": type_id},
        )


@pytest.mark.parametrize("type_id", [2, 3, 4])
def test_nonblocking_unfinished_parent_never_blocks_projection_or_ready(policy_db, type_id):
    edge(policy_db, 21, type_id)
    assert ready(policy_db) is True
    assert dependency_blockers([20]) == {20: []}


def test_all_block_types_gate_execution_and_all_direct_blockers_are_returned(policy_db):
    edge(policy_db, 21, 1)
    edge(policy_db, 22, 1, 2)
    edge(policy_db, 23, 5, 3)
    blockers = dependency_blockers([20])[20]
    assert ready(policy_db) is False
    assert len(blockers) == 2  # closed parent is satisfied; additional blocks type is still enforced
    assert blockers[0]["title"] == "Open"
    assert blockers[1]["accessible"] is False
    assert blockers[1]["card_uid"] is None and blockers[1]["title"] is None
    assert "PRIVATE_FOREIGN_TITLE" not in repr(blockers)


@pytest.mark.parametrize("parent", [23, 24, 999])
def test_inaccessible_or_missing_prerequisite_redacts_identity_and_title(policy_db, parent):
    edge(policy_db, parent, 1)
    blocker = dependency_blockers([20])[20][0]
    assert ready(policy_db) is False
    assert blocker["code"] == "dependency_unavailable"
    assert blocker["accessible"] is False
    assert blocker["card_uid"] is None and blocker["title"] is None
    assert "PRIVATE_" not in repr(blocker)


def test_workflow_mapping_is_authoritative_and_archive_does_not_imply_completion(policy_db):
    edge(policy_db, 22, 1)
    assert ready(policy_db) is True
    assert dependency_blockers([20]) == {20: []}
    with policy_db.begin() as conn:
        conn.execute(text("UPDATE project_column SET workflow_stage='active' WHERE id=12"))
    assert ready(policy_db) is False  # explicit mapping wins over legacy terminal mapping
    with policy_db.begin() as conn:
        conn.execute(text("UPDATE project_column SET workflow_stage='closed' WHERE id=12"))
        conn.execute(text("UPDATE card SET archived_at=now() WHERE id=22"))
    assert ready(policy_db) is False
    assert len(dependency_blockers([20])[20]) == 1


def test_dependency_projection_is_independent_of_external_binding(policy_db):
    edge(policy_db, 21, 1)
    with policy_db.begin() as conn:
        conn.execute(text("DELETE FROM project_execution_binding"))
    assert len(dependency_blockers([20])[20]) == 1
    with policy_db.begin() as conn:
        conn.execute(text("UPDATE card SET project_column_id=12 WHERE id=21"))
    assert dependency_blockers([20]) == {20: []}
    assert ready(policy_db) is False  # no external binding, even when dependencies are clear


@pytest.mark.parametrize("type_id", [2, 3, 4])
def test_nonblocking_binding_cannot_emit_execution(policy_db, type_id):
    with policy_db.begin() as conn:
        conn.execute(
            text("UPDATE project_execution_binding SET prerequisite_relationship_type_id=:type"), {"type": type_id}
        )
    assert ready(policy_db) is False


def test_delete_and_type_change_immediately_recompute_same_policy(policy_db):
    edge(policy_db, 21, 1)
    assert ready(policy_db) is False
    with policy_db.begin() as conn:
        conn.execute(text("UPDATE card_relationship SET relationship_type_id=2 WHERE id=1"))
    assert ready(policy_db) is True
    assert dependency_blockers([20]) == {20: []}
    with policy_db.begin() as conn:
        conn.execute(text("DELETE FROM card_relationship"))
    assert ready(policy_db) is True
