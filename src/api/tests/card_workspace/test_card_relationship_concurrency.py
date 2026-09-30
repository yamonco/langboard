"""PostgreSQL proof that native graph validation and writes serialize per project."""

import os
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import dataclass
from importlib import import_module
from threading import Barrier
from types import SimpleNamespace
from uuid import uuid4
import pytest
from sqlalchemy import column as sa_column
from sqlalchemy import create_engine, select, table, text


os.environ.setdefault("PROJECT_NAME", "langboard")

from langboard_shared.core.db import DbSession  # noqa: E402
from langboard_shared.core.db.DbEngine import DbEngine  # noqa: E402
from langboard_shared.core.types import SnowflakeID  # noqa: E402
from langboard_shared.domain.models import Card, CardRelationship, Project, ProjectColumn  # noqa: E402
from langboard_shared.helpers import InfraHelper  # noqa: E402


relationship_module = import_module("langboard_shared.domain.services.factory.CardRelationshipService")
DATABASE_URL = os.getenv("LANGBOARD_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not DATABASE_URL, reason="requires LANGBOARD_TEST_DATABASE_URL")


@dataclass
class CreatedEdge:
    id: int
    card_id_parent: int
    card_id_child: int

    def api_response(self) -> dict:
        return {"uid": str(self.id)}


@pytest.fixture
def graph_service(monkeypatch: pytest.MonkeyPatch):
    assert DATABASE_URL is not None
    schema = f"card_graph_{uuid4().hex}"
    admin = create_engine(DATABASE_URL)
    with admin.begin() as connection:
        connection.execute(text(f"CREATE SCHEMA {schema}"))
    engine = create_engine(DATABASE_URL, connect_args={"options": f"-csearch_path={schema}"})
    try:
        with engine.begin() as connection:
            connection.execute(text("CREATE TABLE project (id bigint PRIMARY KEY)"))
            connection.execute(text("CREATE TABLE card (id bigint PRIMARY KEY, project_id bigint NOT NULL)"))
            connection.execute(
                text(
                    "CREATE TABLE card_relationship (id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY, "
                    "card_id_parent bigint NOT NULL, card_id_child bigint NOT NULL, "
                    "relationship_type_id bigint NOT NULL)"
                )
            )
            connection.execute(text("INSERT INTO project VALUES (1)"))
            connection.execute(text("INSERT INTO card VALUES (10, 1), (20, 1), (30, 1)"))

        monkeypatch.setattr(DbEngine, "get_main_engine", lambda: engine)
        monkeypatch.setattr(DbEngine, "get_readonly_engine", lambda: engine)
        project = Project.model_construct(id=SnowflakeID(1))
        column = ProjectColumn.model_construct(id=SnowflakeID(5), project_id=project.id, is_archive=False)
        cards = {
            number: Card.model_construct(id=SnowflakeID(number), project_id=project.id, project_column_id=column.id)
            for number in (10, 20, 30)
        }
        by_uid = {card.get_uid(): card for card in cards.values()}
        monkeypatch.setattr(
            InfraHelper,
            "get_records_with_foreign_by_params",
            lambda *params: (project, by_uid.get(params[1][1], cards[10])),
        )

        def get_by_id_like(model, value):
            if model is ProjectColumn:
                return column
            if model is Card:
                return cards.get(int(value)) if isinstance(value, int) else by_uid.get(value)
            raise AssertionError(model)

        monkeypatch.setattr(InfraHelper, "get_by_id_like", get_by_id_like)

        @contextmanager
        def no_readiness():
            yield SimpleNamespace(watch=lambda *_: None, watch_new=lambda *_: None)

        monkeypatch.setattr(relationship_module, "execution_readiness_uow", no_readiness)

        class GraphRepo:
            def get_graph_snapshot(self, _project):
                with DbSession.use(readonly=True) as db:
                    relationship = table(
                        "card_relationship",
                        sa_column("id"),
                        sa_column("card_id_parent"),
                        sa_column("card_id_child"),
                        sa_column("relationship_type_id"),
                    )
                    return db.exec(
                        select(
                            relationship.c.id,
                            relationship.c.card_id_parent,
                            relationship.c.card_id_child,
                            relationship.c.relationship_type_id,
                        )
                    ).all()

            def get_global_relationship_types_map(self, _ids):
                return {
                    SnowflakeID(number): SimpleNamespace(
                        is_active=number != 4,
                        machine_semantic=semantic,
                        api_response=lambda: {"uid": "type"},
                    )
                    for number, semantic in ((1, "blocks"), (2, "contains"), (3, "references"), (4, None))
                    if SnowflakeID(number) in _ids
                }

            def get_all_by_card_and_relation(self, card, relation):
                field = "card_id_child" if relation == "parent" else "card_id_parent"
                with DbSession.use(readonly=True) as db:
                    edge_table = table(
                        "card_relationship",
                        sa_column("id"),
                        sa_column("card_id_parent"),
                        sa_column("card_id_child"),
                        sa_column("relationship_type_id"),
                    )
                    rows = db.exec(
                        select(
                            edge_table.c.id,
                            edge_table.c.card_id_parent,
                            edge_table.c.card_id_child,
                            edge_table.c.relationship_type_id,
                        ).where(edge_table.c[field] == card.id)
                    ).all()
                result = []
                for edge_id, parent, child, type_id in rows:
                    edge = CardRelationship.model_construct(
                        id=SnowflakeID(edge_id),
                        card_id_parent=SnowflakeID(parent),
                        card_id_child=SnowflakeID(child),
                        relationship_type_id=SnowflakeID(type_id),
                    )
                    result.append((edge, None, cards[parent if relation == "parent" else child]))
                return result

            def get_all_related_card_ids(self, project, requested):
                return [card_id for card_id in requested if card_id in cards]

            def delete_all_by_card_and_relation(self, card, relation):
                field = "card_id_child" if relation == "parent" else "card_id_parent"
                with DbSession.use(readonly=False) as db:
                    db.exec(text(f"DELETE FROM card_relationship WHERE {field} = :card"), params={"card": card.id})

            def insert(self, edge):
                with DbSession.use(readonly=False) as db:
                    db.exec(
                        text(
                            "INSERT INTO card_relationship (card_id_parent, card_id_child, relationship_type_id) "
                            "VALUES (:parent, :child, :type)"
                        ),
                        params={
                            "parent": edge.card_id_parent,
                            "child": edge.card_id_child,
                            "type": edge.relationship_type_id,
                        },
                    )

            def apply_graph_patch(self, new_cards, existing_card_ids, add_edges, remove_relationship_ids):
                assert not new_cards
                with DbSession.use(readonly=False) as db:
                    for edge_id in remove_relationship_ids:
                        db.exec(text("DELETE FROM card_relationship WHERE id = :id"), params={"id": edge_id})
                created = []
                with DbSession.use(readonly=False) as db:
                    for parent_ref, child_ref, relationship_type_id in add_edges:
                        parent_id, child_id = existing_card_ids[parent_ref], existing_card_ids[child_ref]
                        relationship_id = int(parent_id) * 100 + int(child_id)
                        db.exec(
                            text(
                                "INSERT INTO card_relationship (id, card_id_parent, card_id_child, relationship_type_id) "
                                "OVERRIDING SYSTEM VALUE VALUES (:id, :parent_id, :child_id, :type_id)"
                            ),
                            params={
                                "id": relationship_id,
                                "parent_id": parent_id,
                                "child_id": child_id,
                                "type_id": relationship_type_id,
                            },
                        )
                        created.append(CreatedEdge(relationship_id, parent_id, child_id))
                return created

        repository = SimpleNamespace(card_relationship=GraphRepo())
        service = relationship_module.CardRelationshipService(lambda *_: None, lambda *_: None, repository)
        monkeypatch.setattr(service, "get_api_list_by_card", lambda *_: [])
        monkeypatch.setattr(service, "_mark_card_changed_for_unread", lambda *_: None)
        monkeypatch.setattr(service, "dispatch_updated", lambda *_args, **_kwargs: None)
        monkeypatch.setattr(service, "_get_service", lambda *_: SimpleNamespace(publish_work_states=lambda *_: None))
        yield service, cards, engine
    finally:
        engine.dispose()
        with admin.begin() as connection:
            connection.execute(text(f"DROP SCHEMA IF EXISTS {schema} CASCADE"))
        admin.dispose()


@pytest.mark.parametrize(
    ("requested_edges", "rejected_reason"),
    [
        (((10, 20), (20, 10)), "Relationship would create a blocks cycle"),
        (((10, 20), (10, 20)), "Relationship already exists"),
    ],
)
def test_concurrent_graph_patches_reject_cycle_or_duplicate(graph_service, requested_edges, rejected_reason) -> None:
    service, cards, engine = graph_service
    start = Barrier(2)

    def apply(edge):
        start.wait()
        return service.apply_graph_patch(
            object(),
            "project",
            "anchor",
            [],
            [(cards[edge[0]].get_uid(), cards[edge[1]].get_uid(), SnowflakeID(1).to_short_code())],
            [],
            dispatch_effects=False,
        )

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(apply, edge) for edge in requested_edges]
        outcomes = []
        for future in futures:
            try:
                outcomes.append(future.result(timeout=10))
            except ValueError as error:
                outcomes.append(str(error))
    assert len([item for item in outcomes if isinstance(item, dict)]) == 1
    assert rejected_reason in outcomes
    with engine.connect() as connection:
        edges = connection.execute(text("SELECT card_id_parent, card_id_child FROM card_relationship")).all()
    assert len(edges) == 1
    assert relationship_module.CardRelationshipService._has_cycle(set(edges)) is False


def test_concurrent_additive_patches_preserve_both_edges(graph_service) -> None:
    service, cards, engine = graph_service
    start = Barrier(2)

    def apply(child_id):
        start.wait()
        return service.apply_graph_patch(
            object(),
            "project",
            "anchor",
            [],
            [(cards[10].get_uid(), cards[child_id].get_uid(), SnowflakeID(1).to_short_code())],
            [],
            dispatch_effects=False,
        )

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(apply, child_id) for child_id in (20, 30)]
        for future in futures:
            assert future.result(timeout=10) is not None
    with engine.connect() as connection:
        edges = connection.execute(
            text("SELECT card_id_parent, card_id_child FROM card_relationship ORDER BY card_id_child")
        ).all()
    assert edges == [(10, 20), (10, 30)]


@pytest.mark.parametrize("semantic_type", [2, 3, 4])
def test_nonblocking_path_does_not_reject_blocking_back_edge(graph_service, semantic_type):
    service, cards, engine = graph_service
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO card_relationship (card_id_parent, card_id_child, relationship_type_id) "
                "VALUES (10, 20, :type), (20, 30, 1)"
            ),
            {"type": semantic_type},
        )
    assert service.apply_graph_patch(
        object(),
        "project",
        "anchor",
        [],
        [(cards[30].get_uid(), cards[10].get_uid(), SnowflakeID(1).to_short_code())],
        [],
        dispatch_effects=False,
    )
    with engine.connect() as connection:
        assert connection.execute(text("SELECT COUNT(*) FROM card_relationship")).scalar_one() == 3


@pytest.mark.parametrize("type_id", [2, 3])
def test_reciprocal_nonblocking_edges_survive_both_write_paths(graph_service, type_id):
    service, cards, engine = graph_service
    uid = SnowflakeID(type_id).to_short_code()
    service.apply_graph_patch(
        object(), "project", "anchor", [], [(cards[10].get_uid(), cards[20].get_uid(), uid)], [], dispatch_effects=False
    )
    service.update(object(), "project", cards[20].get_uid(), False, [(cards[10].get_uid(), uid)])
    with engine.connect() as connection:
        assert connection.execute(text("SELECT COUNT(*) FROM card_relationship")).scalar_one() == 2


def test_direct_replacement_rejects_three_hop_cycle_without_deleting_old_edge(graph_service):
    service, cards, engine = graph_service
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO card_relationship (card_id_parent, card_id_child, relationship_type_id) "
                "VALUES (10, 20, 1), (20, 30, 1), (30, 10, 3)"
            )
        )
    with pytest.raises(ValueError, match="blocks cycle"):
        service.update(
            object(), "project", cards[30].get_uid(), False, [(cards[10].get_uid(), SnowflakeID(1).to_short_code())]
        )
    with engine.connect() as connection:
        assert (
            connection.execute(
                text("SELECT relationship_type_id FROM card_relationship WHERE card_id_parent=30")
            ).scalar_one()
            == 3
        )


def test_direct_and_graph_writers_serialize_block_cycle_validation(graph_service):
    service, cards, engine = graph_service
    start = Barrier(2)
    uid = SnowflakeID(1).to_short_code()

    def graph():
        start.wait()
        return service.apply_graph_patch(
            object(),
            "project",
            "anchor",
            [],
            [(cards[10].get_uid(), cards[20].get_uid(), uid)],
            [],
            dispatch_effects=False,
        )

    def direct():
        start.wait()
        return service.update(object(), "project", cards[20].get_uid(), False, [(cards[10].get_uid(), uid)])

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(graph), executor.submit(direct)]
        outcomes = []
        for future in futures:
            try:
                outcomes.append(future.result(timeout=10))
            except ValueError as error:
                outcomes.append(str(error))
    assert sum(isinstance(item, str) and "blocks cycle" in item for item in outcomes) == 1
    with engine.connect() as connection:
        assert connection.execute(text("SELECT COUNT(*) FROM card_relationship")).scalar_one() == 1


def test_graph_removal_is_applied_before_block_cycle_validation(graph_service):
    service, cards, engine = graph_service
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO card_relationship (id, card_id_parent, card_id_child, relationship_type_id) "
                "OVERRIDING SYSTEM VALUE VALUES (100,10,20,1),(101,20,30,1)"
            )
        )
    assert service.apply_graph_patch(
        object(),
        "project",
        "anchor",
        [],
        [(cards[30].get_uid(), cards[10].get_uid(), SnowflakeID(1).to_short_code())],
        [SnowflakeID(100).to_short_code()],
        dispatch_effects=False,
    )
    with engine.connect() as connection:
        assert connection.execute(text("SELECT COUNT(*) FROM card_relationship WHERE id=100")).scalar_one() == 0
