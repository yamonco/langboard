"""Bounded, privacy-preserving projections for the card workspace contract."""

from __future__ import annotations
from json import dumps
from typing import Any, Iterable, Sequence
from langboard_shared.domain.models.bases import REACTION_TYPES
from ..domain import (
    MAX_CHECKITEMS_PER_CHECKLIST,
    MAX_METADATA_VALUE_CHARS,
    MAX_TEXT_CHARS,
    CardBundleSection,
    SectionCursor,
    is_public_metadata_key,
    projection_revision,
)
from .dtos import BoundedItemsDto, BoundedTextDto


_ACTOR_KEYS = ("uid", "type", "firstname", "lastname", "username", "name", "bot_uname", "avatar")
_CARD_KEYS = ("uid", "title", "created_at", "updated_at")
_WORKFLOW_KEYS = ("project_column_uid", "project_column_name", "order", "deadline_at", "archived_at")
_LABEL_KEYS = ("uid", "name", "color", "description", "order")
_RELATIONSHIP_KEYS = (
    "uid",
    "relationship_type_uid",
    "parent_card_uid",
    "child_card_uid",
    "card_uid_parent",
    "card_uid_child",
)
_CHECKLIST_KEYS = ("uid", "title", "order", "is_checked", "created_at", "updated_at")
_CHECKITEM_KEYS = (
    "uid",
    "title",
    "order",
    "is_checked",
    "deadline_at",
    "status",
    "created_at",
    "updated_at",
)
_ATTACHMENT_KEYS = ("uid", "name", "filename", "order", "created_at", "updated_at")
_COMMENT_KEYS = ("uid", "content", "created_at", "updated_at")
_BOT_SCOPE_KEYS = ("uid", "bot_uid", "card_uid", "is_frozen", "conditions")
_BOT_SCHEDULE_KEYS = (
    "uid",
    "bot_uid",
    "card_uid",
    "running_type",
    "status",
    "interval_str",
    "start_at",
    "end_at",
    "created_at",
    "updated_at",
)
_MAX_FIELD_CHARS = 1_000


def pick(source: dict[str, Any], keys: Iterable[str]) -> dict[str, Any]:
    """Copy only explicitly approved fields from a native response."""

    result: dict[str, Any] = {}
    for key in keys:
        if key not in source:
            continue
        value = source.get(key)
        if isinstance(value, str) and len(value) > _MAX_FIELD_CHARS:
            result[key] = value[:_MAX_FIELD_CHARS]
            result[f"{key}_total_chars"] = len(value)
            result[f"{key}_truncated"] = True
        else:
            result[key] = value
    return result


def public_actor(actor: Any) -> dict[str, Any]:
    """Project an actor without email, credentials, roles, or provider internals."""

    return pick(actor if isinstance(actor, dict) else {}, _ACTOR_KEYS)


def public_comment(comment: dict[str, Any]) -> dict[str, Any]:
    """Project one comment and its public author identity."""

    result = pick(comment, ("uid", "created_at", "updated_at"))
    content, content_format, total_chars = _bounded_inline(comment.get("content"), MAX_TEXT_CHARS)
    result["content"] = content
    result["content_format"] = content_format
    result["content_total_chars"] = total_chars
    result["content_truncated"] = total_chars > len(content)
    for actor_type in ("user", "bot"):
        if isinstance(comment.get(actor_type), dict):
            result[actor_type] = public_actor(comment[actor_type])
    reactions = comment.get("reactions")
    if isinstance(reactions, dict):
        result["reactions"] = {
            reaction_type: [str(actor_uid) for actor_uid in actor_uids[:100]]
            for reaction_type in REACTION_TYPES
            if isinstance((actor_uids := reactions.get(reaction_type)), list) and actor_uids
        }
        result["reaction_counts"] = {
            reaction_type: len(actor_uids)
            for reaction_type in REACTION_TYPES
            if isinstance((actor_uids := reactions.get(reaction_type)), list) and actor_uids
        }
    return result


def public_attachment(attachment: dict[str, Any]) -> dict[str, Any]:
    """Project attachment metadata without bytes, storage paths, or user email."""

    result = pick(attachment, _ATTACHMENT_KEYS)
    if isinstance(attachment.get("user"), dict):
        result["user"] = public_actor(attachment["user"])
    return result


def public_label(label: dict[str, Any]) -> dict[str, Any]:
    """Project one project-defined card label."""

    return pick(label, _LABEL_KEYS)


def public_relationship(relationship: dict[str, Any]) -> dict[str, Any]:
    """Project one native relationship edge."""

    return pick(relationship, _RELATIONSHIP_KEYS)


def public_checkitem(checkitem: dict[str, Any]) -> dict[str, Any]:
    """Project one bounded checklist item."""

    result = pick(checkitem, _CHECKITEM_KEYS)
    if isinstance(checkitem.get("cardified_card"), dict):
        result["cardified_card"] = pick(checkitem["cardified_card"], _CARD_KEYS)
    return result


def public_checklist(checklist: dict[str, Any]) -> dict[str, Any]:
    """Project a checklist while bounding its nested checkitems."""

    result = pick(checklist, _CHECKLIST_KEYS)
    checkitems = [public_checkitem(item) for item in checklist.get("checkitems", []) if isinstance(item, dict)]
    revision = projection_revision(checkitems)
    visible = checkitems[:MAX_CHECKITEMS_PER_CHECKLIST]
    result["checkitems"] = visible
    result["checkitems_total_count"] = len(checkitems)
    result["checkitems_next_cursor"] = (
        SectionCursor(
            section=f"checkitems:{checklist.get('uid', '')}",
            offset=MAX_CHECKITEMS_PER_CHECKLIST,
            revision=revision,
        ).encode()
        if len(checkitems) > MAX_CHECKITEMS_PER_CHECKLIST
        else None
    )
    return result


def public_bot_scope(scope: dict[str, Any]) -> dict[str, Any]:
    """Project the non-secret parts of one native bot scope."""

    result = pick(scope, tuple(key for key in _BOT_SCOPE_KEYS if key != "conditions"))
    if "conditions" in scope:
        conditions, content_format, total_chars = _bounded_inline(scope.get("conditions"), MAX_TEXT_CHARS)
        result["conditions"] = conditions
        result["conditions_format"] = content_format
        result["conditions_total_chars"] = total_chars
        result["conditions_truncated"] = total_chars > len(conditions)
    return result


def public_bot_schedule(schedule: dict[str, Any]) -> dict[str, Any]:
    """Project the non-secret parts of one native bot schedule."""

    return pick(schedule, _BOT_SCHEDULE_KEYS)


def public_card_summary(card: dict[str, Any]) -> dict[str, Any]:
    """Project one minimal card list item."""

    result = pick(card, _CARD_KEYS + _WORKFLOW_KEYS)
    if "member_uids" in card:
        result["member_uids"] = list(card.get("member_uids") or [])[:25]
    return result


def assigned_people(details: dict[str, Any]) -> list[dict[str, Any]]:
    """Return assigned people only, never the full project member directory."""

    assigned = {str(uid) for uid in details.get("member_uids", [])}
    return [
        public_actor(member)
        for member in details.get("project_members", [])
        if isinstance(member, dict) and str(member.get("uid")) in assigned
    ]


def bounded_items(
    items: Sequence[dict[str, Any]],
    section: str | CardBundleSection,
    limit: int,
    offset: int = 0,
    expected_revision: str | None = None,
) -> BoundedItemsDto:
    """Return one bounded offset page tied to an immutable projection revision."""

    normalized = list(items)
    revision = projection_revision(normalized)
    if expected_revision is not None and expected_revision != revision:
        raise ValueError("Section cursor is stale; restart from the first page")
    page = normalized[offset : offset + limit]
    next_offset = offset + len(page)
    next_cursor = (
        SectionCursor(section=str(section), offset=next_offset, revision=revision).encode()
        if next_offset < len(normalized)
        else None
    )
    return BoundedItemsDto(items=page, total_count=len(normalized), next_cursor=next_cursor, limit=limit)


def bounded_text(
    value: Any,
    section: str | CardBundleSection,
    offset: int = 0,
    expected_revision: str | None = None,
) -> BoundedTextDto:
    """Return one bounded, deterministic JSON/text fragment."""

    if isinstance(value, str):
        content = value
        content_format = "text"
    elif value is None:
        content = ""
        content_format = "text"
    else:
        content = dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True, default=str)
        content_format = "json"
    revision = projection_revision(content)
    if expected_revision is not None and expected_revision != revision:
        raise ValueError("Section cursor is stale; restart from the first page")
    fragment = content[offset : offset + MAX_TEXT_CHARS]
    next_offset = offset + len(fragment)
    next_cursor = (
        SectionCursor(section=str(section), offset=next_offset, revision=revision).encode()
        if next_offset < len(content)
        else None
    )
    return BoundedTextDto(
        content=fragment,
        format=content_format,
        total_chars=len(content),
        next_cursor=next_cursor,
    )


def public_metadata(metadata: dict[str, Any]) -> list[dict[str, Any]]:
    """Project only public metadata, bounding every value independently."""

    result: list[dict[str, Any]] = []
    for key in sorted(metadata):
        if not is_public_metadata_key(key):
            continue
        raw = metadata[key]
        value = raw if isinstance(raw, str) else dumps(raw, ensure_ascii=False, default=str)
        result.append(
            {
                "key": key,
                "value": value[:MAX_METADATA_VALUE_CHARS],
                "total_chars": len(value),
                "truncated": len(value) > MAX_METADATA_VALUE_CHARS,
            }
        )
    return result


def _bounded_inline(value: Any, limit: int) -> tuple[str, str, int]:
    """Serialize and cap a nested value that has no independent continuation."""

    if isinstance(value, str):
        content = value
        content_format = "text"
    elif value is None:
        content = ""
        content_format = "text"
    else:
        content = dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True, default=str)
        content_format = "json"
    return content[:limit], content_format, len(content)
