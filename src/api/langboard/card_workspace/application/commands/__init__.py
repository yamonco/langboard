"""State-changing use cases for the card workspace feature."""

from typing import Any
from ...domain import (
    MAX_CHECKITEMS_PER_CHECKLIST,
    MAX_GRAPH_EDGE_CHANGES,
    MAX_GRAPH_NEW_CARDS,
    CardDescriptionPatch,
    CardGraphEdge,
    CardGraphNewCard,
    ChecklistProjectionItem,
    ExactTextReplacement,
    projection_revision,
    require_projection_key,
)
from ...domain import (
    MAX_METADATA_VALUE_CHARS as MAX_METADATA_VALUE_CHARS,
)
from ...domain import (
    MAX_SECTION_LIMIT as MAX_SECTION_LIMIT,
)
from ...domain import (
    MAX_TEXT_CHARS as MAX_TEXT_CHARS,
)
from ..ports import CardWorkspaceCommandPort
from ..projections import (
    public_card_summary,
    public_checklist,
    public_label,
    public_relationship,
)


def provision_project(
    port: CardWorkspaceCommandPort,
    title: str,
    description: str | None = None,
    template_name: str | None = None,
    infer_template_prefix: bool = False,
) -> dict[str, Any]:
    """Create a project with the native standard workflow."""

    normalized_template = _required_text(template_name, "Template name") if template_name is not None else None
    return port.provision_project(
        _required_text(title, "Project title"),
        description,
        normalized_template,
        infer_template_prefix,
    )


def create_card_in_leftmost_column(
    port: CardWorkspaceCommandPort,
    project_uid: str,
    title: str,
    description: str | None = None,
    assign_user_uids: list[str] | None = None,
) -> dict[str, Any]:
    """Create a card in the server-selected leftmost active column."""

    return port.create_card_in_leftmost_column(
        project_uid,
        _required_text(title, "Card title"),
        description,
        _unique_uids(assign_user_uids, "assign_user_uids") if assign_user_uids is not None else None,
    )


def apply_card_graph_patch(
    port: CardWorkspaceCommandPort,
    project_uid: str,
    anchor_card_uid: str,
    new_cards: list[CardGraphNewCard],
    add_edges: list[CardGraphEdge],
    remove_relationship_uids: list[str],
) -> dict[str, Any]:
    """Validate and atomically apply one bounded card relationship graph patch."""

    if not new_cards and not add_edges and not remove_relationship_uids:
        raise ValueError("Graph patch must contain at least one change")
    if len(new_cards) > MAX_GRAPH_NEW_CARDS:
        raise ValueError(f"Graph patch cannot create more than {MAX_GRAPH_NEW_CARDS} cards")
    if len(add_edges) + len(remove_relationship_uids) > MAX_GRAPH_EDGE_CHANGES:
        raise ValueError(f"Graph patch cannot change more than {MAX_GRAPH_EDGE_CHANGES} relationships")

    client_refs = [card.client_ref for card in new_cards]
    if len(client_refs) != len(set(client_refs)):
        raise ValueError("New card client_ref values contain duplicates")
    edge_keys = [(edge.parent_ref, edge.child_ref, edge.relationship_type_uid) for edge in add_edges]
    if len(edge_keys) != len(set(edge_keys)):
        raise ValueError("Graph patch contains duplicate relationship additions")
    removals = [_required_text(uid, "Relationship UID") for uid in remove_relationship_uids]
    if len(removals) != len(set(removals)):
        raise ValueError("Graph patch contains duplicate relationship removals")

    return port.apply_card_graph_patch(
        _required_text(project_uid, "Project UID"),
        _required_text(anchor_card_uid, "Anchor card UID"),
        [CardGraphNewCard(card.client_ref, card.title.strip(), card.description) for card in new_cards],
        add_edges,
        removals,
    )


def patch_card_description(
    port: CardWorkspaceCommandPort,
    project_uid: str,
    card_uid: str,
    edits: list[ExactTextReplacement],
    expected_revision: str | None = None,
) -> dict[str, Any]:
    """Apply one atomic, conflict-detecting Markdown patch."""

    content = port.patch_card_description(
        project_uid,
        card_uid,
        CardDescriptionPatch(tuple(edits), expected_revision),
    )
    return {
        "changed": True,
        "description_revision": projection_revision(content),
        "description_chars": len(content),
        "applied_edits": len(edits),
    }


def replace_card_description(
    port: CardWorkspaceCommandPort,
    project_uid: str,
    card_uid: str,
    description: str,
    expected_revision: str,
) -> dict[str, Any]:
    """Replace the complete reviewed description without losing concurrent edits."""

    content = port.replace_card_description(project_uid, card_uid, description, expected_revision)
    return {
        "changed": True,
        "description_revision": projection_revision(content),
        "description_chars": len(content),
    }


def cardify_card_checkitem(
    port: CardWorkspaceCommandPort,
    project_uid: str,
    card_uid: str,
    checkitem_uid: str,
    project_column_uid: str,
) -> dict[str, Any]:
    """Create and return a bounded card from one existing checkitem."""

    normalized_checkitem_uid = _required_text(checkitem_uid, "Checkitem UID")
    card = port.cardify_card_checkitem(
        _required_text(project_uid, "Project UID"),
        _required_text(card_uid, "Card UID"),
        normalized_checkitem_uid,
        _required_text(project_column_uid, "Project column UID"),
    )
    return {"card": public_card_summary(card), "source_checkitem_uid": normalized_checkitem_uid}


def set_card_people_and_labels(
    port: CardWorkspaceCommandPort,
    project_uid: str,
    card_uid: str,
    assign_user_uids: list[str] | None,
    label_uids: list[str] | None,
) -> dict[str, Any]:
    """Replace people and labels after validating the complete request shape."""

    if assign_user_uids is None and label_uids is None:
        raise ValueError("At least one member or label field is required")
    people = _unique_uids(assign_user_uids, "assign_user_uids") if assign_user_uids is not None else None
    labels = _unique_uids(label_uids, "label_uids") if label_uids is not None else None
    result = port.replace_card_people_and_labels(project_uid, card_uid, people, labels)
    if "labels" in result:
        result["labels"] = [public_label(item) for item in result["labels"]]
    return result


def set_card_relationships(
    port: CardWorkspaceCommandPort,
    project_uid: str,
    card_uid: str,
    is_parent: bool,
    relationships: list[tuple[str, str]],
) -> dict[str, Any]:
    """Replace one relationship direction after validating every requested edge."""

    _optional_bool(is_parent, "is_parent", required=True)
    normalized: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for edge in relationships:
        if not isinstance(edge, (tuple, list)) or len(edge) != 2:
            raise ValueError("Each relationship must contain a card UID and relationship type UID")
        related_uid = _required_text(edge[0], "Related card UID")
        relationship_uid = _required_text(edge[1], "Relationship type UID")
        pair = (related_uid, relationship_uid)
        if pair in seen:
            raise ValueError("Duplicate relationship")
        seen.add(pair)
        normalized.append(pair)
    result = port.replace_card_relationships(project_uid, card_uid, is_parent, normalized)
    return {"relationships": [public_relationship(item) for item in result][:25]}


def reconcile_card_checklist_projection(
    port: CardWorkspaceCommandPort,
    project_uid: str,
    card_uid: str,
    projection_key: str,
    title: str,
    items: list[ChecklistProjectionItem],
    expected_receipt: str | None = None,
) -> dict[str, Any]:
    """Converge one integration-owned checklist without title matching."""

    normalized_key = require_projection_key(projection_key)
    normalized_title = _required_text(title, "Checklist title")
    if len(items) > MAX_CHECKITEMS_PER_CHECKLIST:
        raise ValueError(f"Checklist projection exceeds {MAX_CHECKITEMS_PER_CHECKLIST} items")
    item_keys = [item.key for item in items]
    if len(item_keys) != len(set(item_keys)):
        raise ValueError("Checklist projection item keys contain duplicates")
    if expected_receipt is not None and (
        len(expected_receipt) != 64 or any(character not in "0123456789abcdef" for character in expected_receipt)
    ):
        raise ValueError("Expected checklist projection receipt is invalid")
    result = port.reconcile_card_checklist_projection(
        project_uid,
        card_uid,
        normalized_key,
        normalized_title,
        items,
        expected_receipt,
    )
    return {
        "changed": bool(result["changed"]),
        "receipt": str(result["receipt"]),
        "checklist": public_checklist(result["checklist"]),
    }


def _required_text(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} is required")
    return value.strip()


def _optional_bool(value: bool | None, label: str, required: bool = False) -> None:
    if required and not isinstance(value, bool):
        raise ValueError(f"{label} must be a boolean")
    if value is not None and not isinstance(value, bool):
        raise ValueError(f"{label} must be a boolean")


def _unique_uids(values: list[str] | None, label: str) -> list[str]:
    normalized = [_required_text(value, label) for value in values or []]
    if len(normalized) != len(set(normalized)):
        raise ValueError(f"{label} contains duplicates")
    return normalized
