"""Side-effect-free read use cases for the card workspace feature."""

from typing import Any
from ...domain import (
    CardBundleInclude,
    CardBundleSection,
    CommentCursor,
    CommentPage,
    ProjectCardCursor,
    SectionCursor,
    SectionPage,
    require_public_metadata_key,
)
from ..dtos import (
    AutomationDto,
    BoundedItemsDto,
    CardBundleContinuationDto,
    CardBundleDto,
    CardBundleResponse,
    ClassificationDto,
    ProjectCardListResponse,
    ProjectIdentityResponse,
)
from ..ports import CardBundleSource, CardWorkspaceQueryPort
from ..projections import (
    assigned_people,
    bounded_items,
    bounded_text,
    pick,
    public_attachment,
    public_bot_schedule,
    public_bot_scope,
    public_card_summary,
    public_checklist,
    public_comment,
    public_label,
    public_metadata,
    public_relationship,
)


def get_card_bundle(
    port: CardWorkspaceQueryPort,
    project_uid: str,
    card_uid: str,
    comment_page: CommentPage,
    section_page: SectionPage,
    include: list[CardBundleInclude] | None = None,
) -> CardBundleResponse:
    """Return one bounded and sanitized card aggregate or one continuation page."""

    section_cursor = SectionCursor.decode(section_page.cursor) if section_page.cursor else None
    requested_sections = _requested_source_sections(include, section_cursor, comment_page.cursor is not None)
    source = port.get_card_bundle_source(project_uid, card_uid, requested_sections)
    if source is None:
        raise ValueError("Card not found in project")

    if section_cursor:
        return _section_continuation(card_uid, source, section_cursor, section_page.limit)

    comment_cursor = CommentCursor.decode(comment_page.cursor) if comment_page.cursor else None
    comments = port.get_comment_page(
        card_uid,
        comment_page.limit,
        comment_cursor.created_at if comment_cursor else None,
        comment_cursor.comment_uid if comment_cursor else None,
    )
    comment_projection = _comment_page(
        comments.items, comments.total_count, comments.next_cursor_fields, comment_page.limit
    )
    if comment_page.cursor:
        return CardBundleResponse(
            card_uid=card_uid,
            continuation=CardBundleContinuationDto(section="comments", page=comment_projection),
        )

    details = source.details
    labels = [public_label(item) for item in details.get("labels", []) if isinstance(item, dict)]
    relationships = [public_relationship(item) for item in details.get("relationships", []) if isinstance(item, dict)]
    checklists = [public_checklist(item) for item in source.checklists if isinstance(item, dict)]
    core = pick(details, ("uid", "title", "created_at", "updated_at"))
    core["description"] = bounded_text(details.get("description"), CardBundleSection.CoreDescription).model_dump(
        mode="json"
    )
    bundle = CardBundleDto(
        core=core,
        workflow=pick(
            details,
            ("project_column_uid", "project_column_name", "order", "deadline_at", "archived_at"),
        ),
        people=bounded_items(assigned_people(details), CardBundleSection.People, section_page.limit),
        classification=ClassificationDto(
            labels=bounded_items(labels, CardBundleSection.Labels, section_page.limit),
            relationships=bounded_items(relationships, CardBundleSection.Relationships, section_page.limit),
        ),
        checklists=bounded_items(checklists, CardBundleSection.Checklists, section_page.limit),
        comments=comment_projection,
    )
    requested = set(include or [])
    if CardBundleInclude.Attachments in requested:
        bundle.attachments = bounded_items(
            [public_attachment(item) for item in source.attachments if isinstance(item, dict)],
            CardBundleSection.Attachments,
            section_page.limit,
        )
    if CardBundleInclude.Metadata in requested:
        bundle.metadata = bounded_items(
            public_metadata(source.metadata),
            CardBundleSection.Metadata,
            section_page.limit,
        )
    if CardBundleInclude.Automation in requested:
        bundle.automation = AutomationDto(
            bot_scopes=bounded_items(
                [public_bot_scope(item) for item in source.bot_scopes if isinstance(item, dict)],
                CardBundleSection.BotScopes,
                section_page.limit,
            ),
            bot_schedules=bounded_items(
                [public_bot_schedule(item) for item in source.bot_schedules if isinstance(item, dict)],
                CardBundleSection.BotSchedules,
                section_page.limit,
            ),
        )
    return CardBundleResponse(card_uid=card_uid, card=bundle)


def get_project_identity(port: CardWorkspaceQueryPort, project_uid: str) -> ProjectIdentityResponse:
    """Return the minimum stable identity needed to bind a room to a project."""

    project = port.get_project_identity(project_uid)
    if project is None:
        raise ValueError("Project not found")
    return ProjectIdentityResponse.model_validate(project)


def list_project_cards(
    port: CardWorkspaceQueryPort,
    project_uid: str,
    limit: int = 20,
    cursor: str | None = None,
) -> ProjectCardListResponse:
    """List a bounded, newest-updated-first project card page."""

    if isinstance(limit, bool) or not 1 <= limit <= 25:
        raise ValueError("limit must be between 1 and 25")
    decoded = ProjectCardCursor.decode(cursor) if cursor else None
    page = port.get_project_card_page(
        project_uid,
        limit,
        decoded.updated_at if decoded else None,
        decoded.card_uid if decoded else None,
    )
    next_cursor = ProjectCardCursor(*page.next_cursor_fields).encode() if page.next_cursor_fields else None
    return ProjectCardListResponse(
        project_uid=project_uid,
        cards=BoundedItemsDto(
            items=[public_card_summary(item) for item in page.items],
            total_count=page.total_count,
            next_cursor=next_cursor,
            limit=limit,
        ),
    )


def get_public_card_metadata(
    port: CardWorkspaceQueryPort,
    project_uid: str,
    card_uid: str,
    limit: int = 20,
    cursor: str | None = None,
) -> BoundedItemsDto:
    """Return a bounded list of public card metadata."""

    if isinstance(limit, bool) or not 1 <= limit <= 25:
        raise ValueError("limit must be between 1 and 25")
    metadata = port.get_public_card_metadata(project_uid, card_uid)
    if metadata is None:
        raise ValueError("Card not found in project")
    decoded = SectionCursor.decode(cursor) if cursor else None
    if decoded is not None and decoded.section != CardBundleSection.Metadata:
        raise ValueError("Metadata cursor belongs to another section")
    return bounded_items(
        public_metadata(metadata),
        CardBundleSection.Metadata,
        limit,
        decoded.offset if decoded else 0,
        decoded.revision if decoded else None,
    )


def get_public_card_metadata_by_key(
    port: CardWorkspaceQueryPort, project_uid: str, card_uid: str, key: str
) -> dict[str, Any]:
    """Return one public metadata entry by an explicitly safe key."""

    normalized_key = require_public_metadata_key(key)
    metadata = port.get_public_card_metadata(project_uid, card_uid)
    if metadata is None:
        raise ValueError("Card not found in project")
    entries = {entry["key"]: entry for entry in public_metadata(metadata)}
    if normalized_key not in entries:
        raise ValueError("Metadata not found")
    return entries[normalized_key]


def _comment_page(
    items: list[dict[str, Any]],
    total_count: int,
    next_fields: tuple[str, str] | None,
    limit: int,
) -> BoundedItemsDto:
    next_cursor = CommentCursor(*next_fields).encode() if next_fields else None
    return BoundedItemsDto(
        items=[public_comment(item) for item in items[:limit]],
        total_count=total_count,
        next_cursor=next_cursor,
        limit=limit,
    )


def _section_continuation(
    card_uid: str, source: CardBundleSource, cursor: SectionCursor, limit: int
) -> CardBundleResponse:
    details = source.details
    section = cursor.section
    if section == CardBundleSection.CoreDescription:
        text = bounded_text(details.get("description"), section, cursor.offset, cursor.revision)
        continuation = CardBundleContinuationDto(section=section, text=text)
    else:
        collections: dict[str, list[dict[str, Any]]] = {
            CardBundleSection.People: assigned_people(details),
            CardBundleSection.Labels: [
                public_label(item) for item in details.get("labels", []) if isinstance(item, dict)
            ],
            CardBundleSection.Relationships: [
                public_relationship(item) for item in details.get("relationships", []) if isinstance(item, dict)
            ],
            CardBundleSection.Checklists: [
                public_checklist(item) for item in source.checklists if isinstance(item, dict)
            ],
            CardBundleSection.Attachments: [
                public_attachment(item) for item in source.attachments if isinstance(item, dict)
            ],
            CardBundleSection.Metadata: public_metadata(source.metadata),
            CardBundleSection.BotScopes: [
                public_bot_scope(item) for item in source.bot_scopes if isinstance(item, dict)
            ],
            CardBundleSection.BotSchedules: [
                public_bot_schedule(item) for item in source.bot_schedules if isinstance(item, dict)
            ],
        }
        if section.startswith("checkitems:"):
            checklist_uid = section.partition(":")[2]
            raw = next(
                (
                    item.get("checkitems", [])
                    for item in source.checklists
                    if isinstance(item, dict) and item.get("uid") == checklist_uid
                ),
                None,
            )
            if raw is None:
                raise ValueError("Checklist continuation no longer exists")
            from ..projections import public_checkitem

            items = [public_checkitem(item) for item in raw if isinstance(item, dict)]
        else:
            items = collections.get(section)
            if items is None:
                raise ValueError("Unsupported section cursor")
        page = bounded_items(items, section, limit, cursor.offset, cursor.revision)
        continuation = CardBundleContinuationDto(section=section, page=page)
    return CardBundleResponse(card_uid=card_uid, continuation=continuation)


def _requested_source_sections(
    include: list[CardBundleInclude] | None,
    section_cursor: SectionCursor | None,
    is_comment_continuation: bool,
) -> frozenset[str]:
    """Select only the native sections required for this one response shape."""

    if section_cursor is not None:
        return frozenset({section_cursor.section})
    if is_comment_continuation:
        return frozenset()
    sections = {
        CardBundleSection.People.value,
        CardBundleSection.Labels.value,
        CardBundleSection.Relationships.value,
        CardBundleSection.Checklists.value,
    }
    requested = set(include or [])
    if CardBundleInclude.Attachments in requested:
        sections.add(CardBundleSection.Attachments.value)
    if CardBundleInclude.Metadata in requested:
        sections.add(CardBundleSection.Metadata.value)
    if CardBundleInclude.Automation in requested:
        sections.update({CardBundleSection.BotScopes.value, CardBundleSection.BotSchedules.value})
    return frozenset(sections)
