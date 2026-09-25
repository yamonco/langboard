from typing import Any
import pytest
from langboard.card_workspace.application.commands import (
    patch_card_description,
    replace_card_description,
    validate_card_graph_patch,
)
from langboard.card_workspace.domain import CardGraphEdge, CardGraphNewCard, ExactTextReplacement


class FakeCommandPort:
    """Small recording port used to prove application validation order."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[Any, ...]]] = []

    def patch_card_description(self, project_uid: str, card_uid: str, patch: Any) -> str:
        self.calls.append(("patch_card_description", (project_uid, card_uid, patch)))
        return patch.apply("before old after tail")

    def replace_card_description(
        self, project_uid: str, card_uid: str, description: str, expected_revision: str
    ) -> str:
        self.calls.append(("replace_card_description", (project_uid, card_uid, description, expected_revision)))
        return description


def test_description_patch_returns_receipt_without_echoing_the_body() -> None:
    """The mutation result is verifiable while the potentially large body stays bounded."""

    port = FakeCommandPort()

    result = patch_card_description(
        port,
        "p1",
        "c1",
        [
            ExactTextReplacement("old", "new"),
            ExactTextReplacement("tail", "done"),
        ],
    )

    assert result["changed"] is True
    assert result["description_chars"] == len("before new after done")
    assert result["applied_edits"] == 2
    assert len(result["description_revision"]) == 64
    assert "description" not in result


def test_description_replacement_supports_initialization_and_clearing_without_echoing_body() -> None:
    """Whole-body writes stay revision-bound while allowing either side to be empty."""

    port = FakeCommandPort()

    initialized = replace_card_description(port, "p1", "c1", "first body", "a" * 64)
    cleared = replace_card_description(port, "p1", "c1", "", "b" * 64)

    assert initialized["description_chars"] == 10
    assert cleared["description_chars"] == 0
    assert "description" not in initialized
    assert port.calls == [
        ("replace_card_description", ("p1", "c1", "first body", "a" * 64)),
        ("replace_card_description", ("p1", "c1", "", "b" * 64)),
    ]


def test_graph_patch_supports_a_branched_tree_of_existing_and_new_cards() -> None:
    """A graph patch preserves request-local references for one atomic native call."""

    new_cards = [
        CardGraphNewCard("new:research", "Research"),
        CardGraphNewCard("new:api", "API"),
        CardGraphNewCard("new:ui", "UI"),
    ]
    edges = [
        CardGraphEdge("existing-root", "new:research", "blocks"),
        CardGraphEdge("new:research", "new:api", "blocks"),
        CardGraphEdge("new:research", "new:ui", "blocks"),
    ]

    assert validate_card_graph_patch("project", "existing-root", new_cards, edges, ["old-edge"]) == (
        "project",
        "existing-root",
        [(card.client_ref, card.title, card.description) for card in new_cards],
        [(edge.parent_ref, edge.child_ref, edge.relationship_type_uid) for edge in edges],
        ["old-edge"],
    )


def test_graph_patch_rejects_more_than_seven_new_cards_before_mutation() -> None:
    """The shared validator rejects an oversized batch before native mutation."""

    cards = [CardGraphNewCard(f"new:{index}", f"Card {index}") for index in range(8)]

    with pytest.raises(ValueError, match="more than 7"):
        validate_card_graph_patch("project", "anchor", cards, [], [])
