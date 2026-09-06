from typing import Any
import pytest
from langboard.card_workspace.application.commands import (
    apply_card_graph_patch,
    cardify_card_checkitem,
    create_card_in_leftmost_column,
    create_project_board,
    delete_public_card_metadata,
    patch_card_description,
    set_card_people_and_labels,
    update_card_attachment,
)
from langboard.card_workspace.domain import CardGraphEdge, CardGraphNewCard, ExactTextReplacement


class FakeCommandPort:
    """Small recording port used to prove application validation order."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[Any, ...]]] = []

    def create_project_board(
        self,
        title: str,
        description: str | None,
        template_name: str | None,
        infer_template_prefix: bool,
    ) -> dict[str, Any]:
        self.calls.append(("create_project_board", (title, description, template_name, infer_template_prefix)))
        return {"project": {"uid": "p1", "title": title}, "columns": []}

    def create_card_in_leftmost_column(
        self,
        project_uid: str,
        title: str,
        description: str | None,
        assign_user_uids: list[str] | None,
    ) -> dict[str, Any]:
        self.calls.append(("create_card_in_leftmost_column", (project_uid, title, description, assign_user_uids)))
        return {"card": {"uid": "c1", "title": title}, "column": {"uid": "left"}}

    def apply_card_graph_patch(
        self,
        project_uid: str,
        anchor_card_uid: str,
        new_cards: list[CardGraphNewCard],
        add_edges: list[CardGraphEdge],
        remove_relationship_uids: list[str],
    ) -> dict[str, Any]:
        self.calls.append(
            (
                "apply_card_graph_patch",
                (project_uid, anchor_card_uid, new_cards, add_edges, remove_relationship_uids),
            )
        )
        return {"created_cards": [], "created_relationships": [], "removed_relationship_uids": []}

    def cardify_card_checkitem(
        self,
        project_uid: str,
        card_uid: str,
        checkitem_uid: str,
        project_column_uid: str,
    ) -> dict[str, Any]:
        self.calls.append(("cardify_card_checkitem", (project_uid, card_uid, checkitem_uid, project_column_uid)))
        return {"uid": "promoted", "title": "Promoted", "private": "hidden"}

    def patch_card_description(self, project_uid: str, card_uid: str, patch: Any) -> str:
        self.calls.append(("patch_card_description", (project_uid, card_uid, patch)))
        return patch.apply("before old after tail")

    def replace_card_people_and_labels(
        self,
        project_uid: str,
        card_uid: str,
        assign_user_uids: list[str] | None,
        label_uids: list[str] | None,
    ) -> dict[str, Any]:
        self.calls.append(("replace_card_people_and_labels", (project_uid, card_uid, assign_user_uids, label_uids)))
        return {"member_uids": assign_user_uids or [], "labels": []}

    def update_card_attachment(
        self,
        project_uid: str,
        card_uid: str,
        attachment_uid: str,
        name: str | None,
        order: int | None,
    ) -> list[dict[str, Any]]:
        self.calls.append(("update_card_attachment", (project_uid, card_uid, attachment_uid, name, order)))
        return [
            {
                "uid": attachment_uid,
                "name": name or "file.pdf",
                "order": order or 0,
                "storage_key": "private/object",
                "user": {"uid": "u1", "username": "safe", "email": "hidden@example.com"},
            }
        ]

    def delete_public_card_metadata(self, project_uid: str, card_uid: str, keys: list[str]) -> None:
        self.calls.append(("delete_public_card_metadata", (project_uid, card_uid, keys)))


def test_create_commands_normalize_before_calling_port() -> None:
    """The application owns input normalization while the adapter owns native mechanics."""

    port = FakeCommandPort()

    create_project_board(port, " Delivery ")
    create_card_in_leftmost_column(port, "p1", " Task ", assign_user_uids=["u1"])

    assert port.calls == [
        ("create_project_board", ("Delivery", None, None, False)),
        ("create_card_in_leftmost_column", ("p1", "Task", None, ["u1"])),
    ]


def test_cardify_checkitem_returns_bounded_created_card() -> None:
    """Cardification returns the new card identity without leaking unknown native fields."""

    port = FakeCommandPort()

    result = cardify_card_checkitem(port, " project ", " card ", " item ", " column ")

    assert result == {
        "card": {"uid": "promoted", "title": "Promoted"},
        "source_checkitem_uid": "item",
    }
    assert port.calls == [("cardify_card_checkitem", ("project", "card", "item", "column"))]


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


@pytest.mark.parametrize(
    ("invoke", "message"),
    [
        (lambda port: update_card_attachment(port, "p", "c", "a", " renamed ", -1), "non-negative"),
        (
            lambda port: set_card_people_and_labels(port, "p", "c", ["u1", "u1"], None),
            "duplicates",
        ),
        (
            lambda port: delete_public_card_metadata(port, "p", "c", ["api_token"]),
            "reserved or secret-like",
        ),
    ],
)
def test_invalid_multi_field_mutations_never_reach_port(invoke: Any, message: str) -> None:
    """Every supplied field is validated before any infrastructure mutation can occur."""

    port = FakeCommandPort()

    with pytest.raises(ValueError, match=message):
        invoke(port)

    assert port.calls == []


def test_attachment_mutation_response_is_bounded_and_strips_private_fields() -> None:
    """Attachment mutations never echo storage internals or user email."""

    port = FakeCommandPort()

    response = update_card_attachment(port, "p", "c", "a", "report.pdf", 2)
    item = response["attachments"].items[0]

    assert item["user"] == {"uid": "u1", "username": "safe"}
    assert "storage_key" not in item
    assert response["attachments"].limit == 25


def test_graph_patch_supports_a_branched_tree_of_existing_and_new_cards() -> None:
    """A graph patch preserves request-local references for one atomic native call."""

    port = FakeCommandPort()
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

    apply_card_graph_patch(port, "project", "existing-root", new_cards, edges, ["old-edge"])

    assert port.calls == [
        (
            "apply_card_graph_patch",
            ("project", "existing-root", new_cards, edges, ["old-edge"]),
        )
    ]


def test_graph_patch_rejects_more_than_seven_new_cards_before_mutation() -> None:
    """The application bound is enforced before infrastructure can mutate."""

    port = FakeCommandPort()
    cards = [CardGraphNewCard(f"new:{index}", f"Card {index}") for index in range(8)]

    with pytest.raises(ValueError, match="more than 7"):
        apply_card_graph_patch(port, "project", "anchor", cards, [], [])

    assert port.calls == []
