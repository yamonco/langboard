import os
from collections.abc import Callable
import pytest


os.environ.setdefault("PROJECT_NAME", "langboard")

from langboard.card_workspace.domain.value_objects import CardGraphEdge, CardGraphNewCard  # noqa: E402
from langboard_shared.domain.services.factory.CardRelationshipService import CardRelationshipService  # noqa: E402


def test_cycle_detection_handles_a_branched_tree() -> None:
    """Sibling branches remain valid while a back edge is rejected."""

    edges: set[tuple[str | int, str | int]] = {
        (1, "new:research"),
        ("new:research", "new:api"),
        ("new:research", "new:ui"),
    }

    assert CardRelationshipService._all_connected(edges, 1, {"new:research", "new:api", "new:ui"})
    assert CardRelationshipService._has_path(edges, "new:api", 1) is False
    assert CardRelationshipService._has_path(edges, 1, "new:api") is True
    assert CardRelationshipService._has_cycle(edges) is False

    edges.add(("new:api", 1))
    assert CardRelationshipService._has_cycle(edges) is True


def test_disconnected_new_card_is_not_part_of_the_anchor_tree() -> None:
    """Every created card must belong to the approved anchor component."""

    edges: set[tuple[str | int, str | int]] = {(1, "new:child")}

    assert CardRelationshipService._all_connected(edges, 1, {"new:child", "new:orphan"}) is False


@pytest.mark.parametrize(
    "value",
    [
        lambda: CardGraphNewCard("new:child ", "Child"),
        lambda: CardGraphEdge(" parent", "child", "blocks"),
        lambda: CardGraphEdge("parent", "child", "blocks "),
    ],
)
def test_graph_references_must_arrive_normalized(value: Callable[[], object]) -> None:
    """Whitespace cannot create a request-local key that fails later lookups."""

    with pytest.raises(ValueError):
        value()
