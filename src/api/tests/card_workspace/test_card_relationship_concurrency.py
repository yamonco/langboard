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
from langboard_shared.domain.models import Card, Project, ProjectColumn  # noqa: E402
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
        monkeypatch.setattr(InfraHelper, "get_records_with_foreign_by_params", lambda *_: (project, cards[10]))

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
                        "card_relationship", sa_column("id"), sa_column("card_id_parent"), sa_column("card_id_child")
                    )
                    return db.exec(
                        select(relationship.c.id, relationship.c.card_id_parent, relationship.c.card_id_child)
                    ).all()

            def get_global_relationship_types_map(self, _ids):
                return {SnowflakeID(1): object()}

            def apply_graph_patch(self, new_cards, existing_card_ids, add_edges, remove_relationship_ids):
                assert not new_cards and not remove_relationship_ids
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
                            params={"id": relationship_id, "parent_id": parent_id, "child_id": child_id, "type_id": relationship_type_id},
                        )
                        created.append(CreatedEdge(relationship_id, parent_id, child_id))
                return created

        repository = SimpleNamespace(card_relationship=GraphRepo())
        service = relationship_module.CardRelationshipService(lambda *_: None, lambda *_: None, repository)
        yield service, cards, engine
    finally:
        engine.dispose()
        with admin.begin() as connection:
            connection.execute(text(f"DROP SCHEMA IF EXISTS {schema} CASCADE"))
        admin.dispose()


@pytest.mark.parametrize(
    ("requested_edges", "rejected_reason"),
    [
        (((10, 20), (20, 10)), "Graph patch would create a relationship cycle"),
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
