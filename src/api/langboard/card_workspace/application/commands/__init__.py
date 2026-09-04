"""State-changing use cases for the card workspace feature."""

from hashlib import sha256
from typing import Any
from ...domain import (
    MAX_CHECKITEMS_PER_CHECKLIST,
    MAX_GRAPH_EDGE_CHANGES,
    MAX_GRAPH_NEW_CARDS,
    CardBundleSection,
    CardGraphEdge,
    CardGraphNewCard,
    ChecklistProjectionItem,
    ExactTextReplacement,
    require_projection_key,
    require_public_metadata_key,
)
from ..ports import CardWorkspaceCommandPort
from ..projections import (
    bounded_items,
    public_attachment,
    public_card_summary,
    public_checkitem,
    public_checklist,
    public_comment,
    public_label,
    public_metadata,
    public_relationship,
)


def create_project_board(
    port: CardWorkspaceCommandPort,
    title: str,
    description: str | None = None,
    template_name: str | None = None,
    infer_template_prefix: bool = False,
) -> dict[str, Any]:
    """Create a project with the native standard workflow."""

    normalized_template = _required_text(template_name, "Template name") if template_name is not None else None
    return port.create_project_board(
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
    old_text: str,
    new_text: str,
) -> dict[str, Any]:
    """Apply one exact, conflict-detecting card description replacement."""

    content = port.patch_card_description(
        project_uid,
        card_uid,
        ExactTextReplacement(old_text=old_text, new_text=new_text),
    )
    return {
        "changed": True,
        "description_sha256": sha256(content.encode("utf-8")).hexdigest(),
        "description_chars": len(content),
    }


def add_card_comment(port: CardWorkspaceCommandPort, project_uid: str, card_uid: str, content: str) -> dict[str, Any]:
    """Create and return a sanitized card comment."""

    return {"comment": public_comment(port.add_card_comment(project_uid, card_uid, _required_text(content, "Comment")))}


def update_card_comment(
    port: CardWorkspaceCommandPort,
    project_uid: str,
    card_uid: str,
    comment_uid: str,
    content: str,
) -> dict[str, Any]:
    """Update and return a sanitized owned card comment."""

    return {
        "comment": public_comment(
            port.update_card_comment(project_uid, card_uid, comment_uid, _required_text(content, "Comment"))
        )
    }


def delete_card_comment(
    port: CardWorkspaceCommandPort, project_uid: str, card_uid: str, comment_uid: str
) -> dict[str, bool]:
    """Delete one owned card comment."""

    port.delete_card_comment(project_uid, card_uid, comment_uid)
    return {"deleted": True}


def create_card_checklist(
    port: CardWorkspaceCommandPort, project_uid: str, card_uid: str, title: str
) -> dict[str, Any]:
    """Create and return a sanitized native checklist."""

    return {
        "checklist": public_checklist(
            port.create_card_checklist(project_uid, card_uid, _required_text(title, "Checklist title"))
        )
    }


def update_card_checklist(
    port: CardWorkspaceCommandPort,
    project_uid: str,
    card_uid: str,
    checklist_uid: str,
    title: str | None,
    is_checked: bool | None,
) -> dict[str, Any]:
    """Validate all fields before updating a checklist."""

    if title is None and is_checked is None:
        raise ValueError("At least one checklist field is required")
    normalized_title = _required_text(title, "Checklist title") if title is not None else None
    _optional_bool(is_checked, "is_checked")
    checklists = port.update_card_checklist(project_uid, card_uid, checklist_uid, normalized_title, is_checked)
    return {
        "checklists": bounded_items([public_checklist(item) for item in checklists], CardBundleSection.Checklists, 25)
    }


def delete_card_checklist(
    port: CardWorkspaceCommandPort, project_uid: str, card_uid: str, checklist_uid: str
) -> dict[str, bool]:
    """Delete one native checklist."""

    port.delete_card_checklist(project_uid, card_uid, checklist_uid)
    return {"deleted": True}


def create_card_checkitem(
    port: CardWorkspaceCommandPort,
    project_uid: str,
    card_uid: str,
    checklist_uid: str,
    title: str,
) -> dict[str, Any]:
    """Create and return a sanitized checkitem."""

    return {
        "checkitem": public_checkitem(
            port.create_card_checkitem(project_uid, card_uid, checklist_uid, _required_text(title, "Checkitem title"))
        )
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


def update_card_checkitem(
    port: CardWorkspaceCommandPort,
    project_uid: str,
    card_uid: str,
    checkitem_uid: str,
    title: str | None,
    deadline_at: str | None,
    is_checked: bool | None,
) -> dict[str, Any]:
    """Validate all fields before updating a checkitem."""

    if title is None and deadline_at is None and is_checked is None:
        raise ValueError("At least one checkitem field is required")
    normalized_title = _required_text(title, "Checkitem title") if title is not None else None
    _optional_bool(is_checked, "is_checked")
    checklists = port.update_card_checkitem(
        project_uid, card_uid, checkitem_uid, normalized_title, deadline_at, is_checked
    )
    return {
        "checklists": bounded_items([public_checklist(item) for item in checklists], CardBundleSection.Checklists, 25)
    }


def delete_card_checkitem(
    port: CardWorkspaceCommandPort, project_uid: str, card_uid: str, checkitem_uid: str
) -> dict[str, bool]:
    """Delete one native checkitem."""

    port.delete_card_checkitem(project_uid, card_uid, checkitem_uid)
    return {"deleted": True}


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


def update_card_attachment(
    port: CardWorkspaceCommandPort,
    project_uid: str,
    card_uid: str,
    attachment_uid: str,
    name: str | None,
    order: int | None,
) -> dict[str, Any]:
    """Validate all attachment fields before applying any mutation."""

    if name is None and order is None:
        raise ValueError("At least one attachment field is required")
    normalized_name = _required_text(name, "Attachment name") if name is not None else None
    if order is not None and (isinstance(order, bool) or order < 0):
        raise ValueError("Attachment order must be a non-negative integer")
    attachments = port.update_card_attachment(project_uid, card_uid, attachment_uid, normalized_name, order)
    return {
        "attachments": bounded_items(
            [public_attachment(item) for item in attachments], CardBundleSection.Attachments, 25
        )
    }


def delete_card_attachment(
    port: CardWorkspaceCommandPort, project_uid: str, card_uid: str, attachment_uid: str
) -> dict[str, bool]:
    """Delete one attachment without returning file or actor details."""

    port.delete_card_attachment(project_uid, card_uid, attachment_uid)
    return {"deleted": True}


def save_public_card_metadata(
    port: CardWorkspaceCommandPort,
    project_uid: str,
    card_uid: str,
    key: str,
    value: str,
    old_key: str | None = None,
) -> dict[str, Any]:
    """Save public metadata while refusing reserved or secret-like keys."""

    normalized_key = require_public_metadata_key(key)
    normalized_old_key = require_public_metadata_key(old_key) if old_key is not None else None
    metadata = port.save_public_card_metadata(project_uid, card_uid, normalized_key, value, normalized_old_key)
    entries = public_metadata(metadata)
    return next(entry for entry in entries if entry["key"] == normalized_key)


def delete_public_card_metadata(
    port: CardWorkspaceCommandPort,
    project_uid: str,
    card_uid: str,
    keys: list[str],
) -> dict[str, bool]:
    """Delete public metadata keys only."""

    if not keys:
        raise ValueError("At least one metadata key is required")
    normalized = [require_public_metadata_key(key) for key in keys]
    if len(normalized) != len(set(normalized)):
        raise ValueError("Duplicate metadata key")
    port.delete_public_card_metadata(project_uid, card_uid, normalized)
    return {"deleted": True}


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
