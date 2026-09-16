import os
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
import pytest
from sqlalchemy import create_engine, text


os.environ.setdefault("PROJECT_NAME", "langboard")

from langboard_shared.core.db.DbEngine import DbEngine  # noqa: E402
from langboard_shared.core.types import SnowflakeID  # noqa: E402
from langboard_shared.domain.models import Project  # noqa: E402
from langboard_shared.domain.services.factory.CardRelationshipService import CardRelationshipService  # noqa: E402
from langboard_shared.infrastructure.repositories.factory.CardRelationshipRepository import (  # noqa: E402
    CardRelationshipRepository,
)


DATABASE_URL = os.getenv("LANGBOARD_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not DATABASE_URL, reason="requires LANGBOARD_TEST_DATABASE_URL")


@pytest.mark.parametrize(
    ("requested_edges", "rejected_reason"),
    [
        (("left", "right", "right", "left"), "Graph patch would create a relationship cycle"),
        (("left", "right", "left", "right"), "Relationship already exists"),
    ],
)
def test_concurrent_graph_patches_cannot_create_duplicates_or_cycles(
    monkeypatch: pytest.MonkeyPatch,
    requested_edges: tuple[str, str, str, str],
    rejected_reason: str,
) -> None:
    """The project row lock forces the second writer to validate the first committed edge."""

    assert DATABASE_URL is not None
    engine = create_engine(DATABASE_URL)
    with engine.begin() as connection:
        connection.execute(text("DROP TABLE IF EXISTS card_relationship"))
        connection.execute(text("DROP TABLE IF EXISTS card"))
        connection.execute(text("DROP TABLE IF EXISTS project"))
        connection.execute(text("CREATE TABLE project (id BIGINT PRIMARY KEY, deleted_at TIMESTAMP)"))
        connection.execute(
            text("CREATE TABLE card (id BIGINT PRIMARY KEY, project_id BIGINT NOT NULL, deleted_at TIMESTAMP)")
        )
        connection.execute(
            text(
                """
                CREATE TABLE card_relationship (
                    id BIGINT PRIMARY KEY,
                    created_at TIMESTAMP NOT NULL,
                    updated_at TIMESTAMP NOT NULL,
                    relationship_type_id BIGINT NOT NULL,
                    card_id_parent BIGINT NOT NULL,
                    card_id_child BIGINT NOT NULL
                )
                """
            )
        )
        connection.execute(text("INSERT INTO project (id) VALUES (1)"))
        connection.execute(text("INSERT INTO card (id, project_id) VALUES (10, 1), (20, 1)"))

    monkeypatch.setattr(DbEngine, "get_main_engine", lambda: engine)
    repository = CardRelationshipRepository(lambda _type: None, lambda _name: None)
    project = Project.model_construct(id=SnowflakeID(1))
    start = Barrier(2)

    def apply(parent_ref: str, child_ref: str) -> str:
        start.wait()

        def validate(snapshot: list[tuple[int, int, int]]) -> list[tuple[int, int, int]]:
            current_edges = {(parent_id, child_id) for _, parent_id, child_id in snapshot}
            proposed_edge = ({"left": 10, "right": 20}[parent_ref], {"left": 10, "right": 20}[child_ref])
            if proposed_edge in current_edges:
                raise ValueError("Relationship already exists")
            if CardRelationshipService._has_cycle(current_edges | {proposed_edge}):
                raise ValueError("Graph patch would create a relationship cycle")
            return []

        repository.apply_graph_patch(
            project,
            {},
            {"left": 10, "right": 20},
            [(parent_ref, child_ref, 1)],
            validate,
        )
        return "applied"

    try:
        with ThreadPoolExecutor(max_workers=2) as executor:
            results = [
                executor.submit(apply, requested_edges[0], requested_edges[1]),
                executor.submit(apply, requested_edges[2], requested_edges[3]),
            ]
            outcomes = []
            for result in results:
                try:
                    outcomes.append(result.result(timeout=10))
                except ValueError as error:
                    outcomes.append(str(error))

        assert sorted(outcomes) == [rejected_reason, "applied"]
        with engine.connect() as connection:
            edges = connection.execute(
                text("SELECT card_id_parent, card_id_child FROM card_relationship ORDER BY id")
            ).all()
        assert len(edges) == 1
        assert CardRelationshipService._has_cycle(set(edges)) is False
    finally:
        with engine.begin() as connection:
            connection.execute(text("DROP TABLE IF EXISTS card_relationship"))
            connection.execute(text("DROP TABLE IF EXISTS card"))
            connection.execute(text("DROP TABLE IF EXISTS project"))
        engine.dispose()
