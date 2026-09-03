"""Safe native MCP tools for room-bound Langboard project workspaces."""

from typing import Annotated, Any, Literal
from langboard_shared.domain.models import Bot, ProjectRole, User
from langboard_shared.domain.models.ProjectRole import ProjectRoleAction
from langboard_shared.domain.services import DomainService
from langboard_shared.security import RoleFinder
from pydantic import BeforeValidator
from ..card_workspace.application import (
    CardBundleResponse,
    ProjectCardListResponse,
    ProjectIdentityResponse,
)
from ..card_workspace.application import add_card_comment as add_comment
from ..card_workspace.application import apply_card_graph_patch as apply_graph_patch
from ..card_workspace.application import create_card_checkitem as create_checkitem
from ..card_workspace.application import create_card_checklist as create_checklist
from ..card_workspace.application import create_card_in_leftmost_column as create_leftmost
from ..card_workspace.application import create_project_board as create_board
from ..card_workspace.application import delete_card_attachment as delete_attachment
from ..card_workspace.application import delete_card_checkitem as delete_checkitem
from ..card_workspace.application import delete_card_checklist as delete_checklist
from ..card_workspace.application import delete_card_comment as delete_comment
from ..card_workspace.application import delete_public_card_metadata as delete_public_metadata
from ..card_workspace.application import get_card_bundle as query_card_bundle
from ..card_workspace.application import get_project_identity as query_project_identity
from ..card_workspace.application import get_public_card_metadata as query_public_metadata
from ..card_workspace.application import get_public_card_metadata_by_key as query_public_metadata_key
from ..card_workspace.application import list_project_cards as query_project_cards
from ..card_workspace.application import reconcile_card_checklist_projection as reconcile_checklist
from ..card_workspace.application import save_public_card_metadata as save_public_metadata
from ..card_workspace.application import set_card_people_and_labels as replace_people_and_labels
from ..card_workspace.application import set_card_relationships as replace_relationships
from ..card_workspace.application import update_card_attachment as update_attachment
from ..card_workspace.application import update_card_checkitem as update_checkitem
from ..card_workspace.application import update_card_checklist as update_checklist
from ..card_workspace.application import update_card_comment as update_comment
from ..card_workspace.application.dtos import BoundedItemsDto
from ..card_workspace.domain import (
    CardBundleInclude,
    CardGraphEdge,
    CardGraphNewCard,
    ChecklistProjectionItem,
    CommentPage,
    SectionPage,
)
from ..card_workspace.infrastructure import NativeCardWorkspaceAdapter
from ..mcp_integration import McpRoleFilter, McpTool


def _as_card_bundle_include(value: str | CardBundleInclude) -> CardBundleInclude:
    """Parse one JSON enum value without weakening the domain type."""

    return CardBundleInclude(value)


JsonCardBundleInclude = Annotated[CardBundleInclude, BeforeValidator(_as_card_bundle_include)]


def _as_checklist_projection_item(
    value: dict[str, Any] | ChecklistProjectionItem,
) -> ChecklistProjectionItem:
    """Parse one JSON projection item without leaking transport types inward."""

    if isinstance(value, ChecklistProjectionItem):
        return value
    return ChecklistProjectionItem(**value)


JsonChecklistProjectionItem = Annotated[
    ChecklistProjectionItem,
    BeforeValidator(_as_checklist_projection_item),
]

CardCommentReactionType = Literal[
    "check-mark",
    "confusing",
    "eyes",
    "heart",
    "laughing",
    "party-popper",
    "rocket",
    "thumbs-down",
    "thumbs-up",
]


def _as_card_graph_new_card(value: dict[str, Any] | CardGraphNewCard) -> CardGraphNewCard:
    """Parse one request-local card without leaking transport types inward."""

    return value if isinstance(value, CardGraphNewCard) else CardGraphNewCard(**value)


def _as_card_graph_edge(value: dict[str, Any] | CardGraphEdge) -> CardGraphEdge:
    """Parse one typed graph edge without leaking transport types inward."""

    return value if isinstance(value, CardGraphEdge) else CardGraphEdge(**value)


JsonCardGraphNewCard = Annotated[CardGraphNewCard, BeforeValidator(_as_card_graph_new_card)]
JsonCardGraphEdge = Annotated[CardGraphEdge, BeforeValidator(_as_card_graph_edge)]


def _adapter(actor: User | Bot, service: DomainService) -> NativeCardWorkspaceAdapter:
    """Build the native adapter at the MCP composition root."""

    return NativeCardWorkspaceAdapter(actor, service)


@McpTool.add("user", description="Create a project from a named template, or the configured default.")
def create_project_board(
    title: str,
    user: User,
    service: DomainService,
    description: str | None = None,
    template_name: str | None = None,
    infer_template_prefix: bool = False,
) -> dict[str, Any]:
    """Create a template-backed agent-managed project board."""

    return create_board(
        _adapter(user, service),
        title,
        description,
        template_name,
        infer_template_prefix,
    )


@McpTool.add(description="Create a card in the current leftmost non-archive project column.")
@McpRoleFilter.add(ProjectRole, [ProjectRoleAction.CardUpdate], RoleFinder.project)
def create_card_in_leftmost_column(
    project_uid: str,
    title: str,
    user_or_bot: User | Bot,
    service: DomainService,
    description: str | None = None,
    assign_user_uids: list[str] | None = None,
) -> dict[str, Any]:
    """Create a card without trusting a caller-provided destination column."""

    return create_leftmost(_adapter(user_or_bot, service), project_uid, title, description, assign_user_uids)


@McpTool.add(
    description=(
        "Atomically create up to seven cards and add or remove typed parent-child relationships. "
        "References beginning with 'new:' address cards created by this same request."
    )
)
@McpRoleFilter.add(ProjectRole, [ProjectRoleAction.CardUpdate], RoleFinder.project)
def apply_card_graph_patch(
    project_uid: str,
    anchor_card_uid: str,
    new_cards: list[JsonCardGraphNewCard],
    add_edges: list[JsonCardGraphEdge],
    remove_relationship_uids: list[str],
    user_or_bot: User | Bot,
    service: DomainService,
) -> dict[str, Any]:
    """Apply one approved card graph patch without partial persistence."""

    return apply_graph_patch(
        _adapter(user_or_bot, service),
        project_uid,
        anchor_card_uid,
        new_cards,
        add_edges,
        remove_relationship_uids,
    )


@McpTool.add(
    description=(
        "Read compact card core and workflow fields. Request description, people, classification, checklists, "
        "comments, attachments, public metadata, or automation explicitly. Use returned opaque cursors for "
        "rich description and every collection."
    )
)
@McpRoleFilter.add(ProjectRole, [ProjectRoleAction.Read], RoleFinder.project)
def get_card_bundle(
    project_uid: str,
    card_uid: str,
    user_or_bot: User | Bot,
    service: DomainService,
    comments_limit: int = 5,
    comments_cursor: str | None = None,
    section_limit: int = 10,
    section_cursor: str | None = None,
    include: list[JsonCardBundleInclude] | None = None,
) -> CardBundleResponse:
    """Read an agent-friendly card bundle with bounded continuation."""

    return query_card_bundle(
        _adapter(user_or_bot, service),
        project_uid,
        card_uid,
        CommentPage(limit=comments_limit, cursor=comments_cursor),
        SectionPage(limit=section_limit, cursor=section_cursor),
        include,
    )


@McpTool.add(description="Return a project's stable identity and bounded active workflow columns.")
@McpRoleFilter.add(ProjectRole, [ProjectRoleAction.Read], RoleFinder.project)
def get_project_identity(
    project_uid: str,
    user_or_bot: User | Bot,
    service: DomainService,
) -> ProjectIdentityResponse:
    """Read project identity and the active columns required for safe card moves."""

    return query_project_identity(_adapter(user_or_bot, service), project_uid)


@McpTool.add(description="List compact project members without email addresses.")
@McpRoleFilter.add(ProjectRole, [ProjectRoleAction.Read], RoleFinder.project)
def list_project_members(project_uid: str, service: DomainService) -> dict[str, Any]:
    """Return the bounded public member directory needed for assignments."""

    project = service.project.get_by_id_like(project_uid)
    if not project:
        raise ValueError("Project not found")
    members = service.project.get_api_assigned_user_list(project)
    items = [{key: member[key] for key in ("uid", "username") if key in member} for member in members[:50]]
    return {"items": items, "total_count": len(members), "truncated": len(members) > 50}


@McpTool.add(description="List a bounded newest-updated-first page of cards in a project.")
@McpRoleFilter.add(ProjectRole, [ProjectRoleAction.Read], RoleFinder.project)
def list_project_cards(
    project_uid: str,
    user_or_bot: User | Bot,
    service: DomainService,
    limit: int = 20,
    cursor: str | None = None,
) -> ProjectCardListResponse:
    """Read one safe project card page with an opaque keyset cursor."""

    return query_project_cards(_adapter(user_or_bot, service), project_uid, limit, cursor)


@McpTool.add(description="Add a rich-text comment to a card.")
@McpRoleFilter.add(ProjectRole, [ProjectRoleAction.Read], RoleFinder.project)
def add_card_comment(
    project_uid: str,
    card_uid: str,
    content: str,
    user_or_bot: User | Bot,
    service: DomainService,
) -> dict[str, Any]:
    """Add a native card comment."""

    return add_comment(_adapter(user_or_bot, service), project_uid, card_uid, content)


@McpTool.add(description="Toggle one reaction supported by Langboard on a card comment.")
@McpRoleFilter.add(ProjectRole, [ProjectRoleAction.Read], RoleFinder.project)
def toggle_card_comment_reaction(
    project_uid: str,
    card_uid: str,
    comment_uid: str,
    reaction: CardCommentReactionType,
    user_or_bot: User | Bot,
    service: DomainService,
) -> dict[str, bool]:
    """Toggle a native comment reaction after project-card-comment validation."""

    comment = service.card_comment.get_by_id_like(comment_uid)
    if not comment:
        raise ValueError("Card comment not found")
    is_reacted = service.card_comment.toggle_reaction(user_or_bot, project_uid, card_uid, comment, reaction)
    if is_reacted is None:
        raise ValueError("Card comment not found")
    return {"is_reacted": is_reacted}


@McpTool.add(description="Update a card comment owned by the current actor.")
@McpRoleFilter.add(ProjectRole, [ProjectRoleAction.Read], RoleFinder.project)
def update_card_comment(
    project_uid: str,
    card_uid: str,
    comment_uid: str,
    content: str,
    user_or_bot: User | Bot,
    service: DomainService,
) -> dict[str, Any]:
    """Update an owned native comment."""

    return update_comment(_adapter(user_or_bot, service), project_uid, card_uid, comment_uid, content)


@McpTool.add(description="Delete a card comment owned by the current actor.")
@McpRoleFilter.add(ProjectRole, [ProjectRoleAction.Read], RoleFinder.project)
def delete_card_comment(
    project_uid: str,
    card_uid: str,
    comment_uid: str,
    user_or_bot: User | Bot,
    service: DomainService,
) -> dict[str, bool]:
    """Delete an owned native comment."""

    return delete_comment(_adapter(user_or_bot, service), project_uid, card_uid, comment_uid)


@McpTool.add(description="Create a checklist on a card.")
@McpRoleFilter.add(ProjectRole, [ProjectRoleAction.CardUpdate], RoleFinder.project)
def create_card_checklist(
    project_uid: str,
    card_uid: str,
    title: str,
    user_or_bot: User | Bot,
    service: DomainService,
) -> dict[str, Any]:
    """Create a native checklist."""

    return create_checklist(_adapter(user_or_bot, service), project_uid, card_uid, title)


@McpTool.add(description="Update a card checklist title and/or checked state atomically validated.")
@McpRoleFilter.add(ProjectRole, [ProjectRoleAction.CardUpdate], RoleFinder.project)
def update_card_checklist(
    project_uid: str,
    card_uid: str,
    checklist_uid: str,
    user_or_bot: User | Bot,
    service: DomainService,
    title: str | None = None,
    is_checked: bool | None = None,
) -> dict[str, Any]:
    """Update a native checklist after validating every requested field."""

    return update_checklist(
        _adapter(user_or_bot, service),
        project_uid,
        card_uid,
        checklist_uid,
        title,
        is_checked,
    )


@McpTool.add(description="Delete a checklist from a card.")
@McpRoleFilter.add(ProjectRole, [ProjectRoleAction.CardUpdate], RoleFinder.project)
def delete_card_checklist(
    project_uid: str,
    card_uid: str,
    checklist_uid: str,
    user_or_bot: User | Bot,
    service: DomainService,
) -> dict[str, bool]:
    """Delete a native checklist and its checkitems."""

    return delete_checklist(_adapter(user_or_bot, service), project_uid, card_uid, checklist_uid)


@McpTool.add(description="Create a checkitem in a card checklist.")
@McpRoleFilter.add(ProjectRole, [ProjectRoleAction.CardUpdate], RoleFinder.project)
def create_card_checkitem(
    project_uid: str,
    card_uid: str,
    checklist_uid: str,
    title: str,
    user_or_bot: User | Bot,
    service: DomainService,
) -> dict[str, Any]:
    """Create a native checkitem."""

    return create_checkitem(_adapter(user_or_bot, service), project_uid, card_uid, checklist_uid, title)


@McpTool.add(
    description=(
        "Idempotently reconcile one bot-authored checklist by stable keys. "
        "The server checkpoints native identities and writes the content receipt last."
    )
)
@McpRoleFilter.add(ProjectRole, [ProjectRoleAction.CardUpdate], RoleFinder.project)
def reconcile_card_checklist_projection(
    project_uid: str,
    card_uid: str,
    projection_key: str,
    title: str,
    items: list[JsonChecklistProjectionItem],
    user_or_bot: User | Bot,
    service: DomainService,
    expected_receipt: str | None = None,
) -> dict[str, Any]:
    """Converge one integration-owned checklist without title matching."""

    return reconcile_checklist(
        _adapter(user_or_bot, service),
        project_uid,
        card_uid,
        projection_key,
        title,
        items,
        expected_receipt,
    )


@McpTool.add(description="Update checkitem title, deadline, and/or checked state after full validation.")
@McpRoleFilter.add(ProjectRole, [ProjectRoleAction.CardUpdate], RoleFinder.project)
def update_card_checkitem(
    project_uid: str,
    card_uid: str,
    checkitem_uid: str,
    user_or_bot: User | Bot,
    service: DomainService,
    title: str | None = None,
    deadline_at: str | None = None,
    is_checked: bool | None = None,
) -> dict[str, Any]:
    """Update a native checkitem after validating every requested field."""

    return update_checkitem(
        _adapter(user_or_bot, service),
        project_uid,
        card_uid,
        checkitem_uid,
        title,
        deadline_at,
        is_checked,
    )


@McpTool.add(description="Delete a checkitem from a card checklist.")
@McpRoleFilter.add(ProjectRole, [ProjectRoleAction.CardUpdate], RoleFinder.project)
def delete_card_checkitem(
    project_uid: str,
    card_uid: str,
    checkitem_uid: str,
    user_or_bot: User | Bot,
    service: DomainService,
) -> dict[str, bool]:
    """Delete a native checkitem after ancestry validation."""

    return delete_checkitem(_adapter(user_or_bot, service), project_uid, card_uid, checkitem_uid)


@McpTool.add(description="Replace a card's assigned members and/or labels after validating every UID.")
@McpRoleFilter.add(ProjectRole, [ProjectRoleAction.CardUpdate], RoleFinder.project)
def set_card_people_and_labels(
    project_uid: str,
    card_uid: str,
    user_or_bot: User | Bot,
    service: DomainService,
    assign_user_uids: list[str] | None = None,
    label_uids: list[str] | None = None,
) -> dict[str, Any]:
    """Replace optional native member and label sets."""

    return replace_people_and_labels(
        _adapter(user_or_bot, service),
        project_uid,
        card_uid,
        assign_user_uids,
        label_uids,
    )


@McpTool.add(description="Replace one direction of a card's typed relationships after full validation.")
@McpRoleFilter.add(ProjectRole, [ProjectRoleAction.CardUpdate], RoleFinder.project)
def set_card_relationships(
    project_uid: str,
    card_uid: str,
    is_parent: bool,
    relationships: list[tuple[str, str]],
    user_or_bot: User | Bot,
    service: DomainService,
) -> dict[str, Any]:
    """Replace native parent or child relationship edges."""

    return replace_relationships(_adapter(user_or_bot, service), project_uid, card_uid, is_parent, relationships)


@McpTool.add("user", description="Update attachment name and/or order without bytes or user email.")
@McpRoleFilter.add(ProjectRole, [ProjectRoleAction.CardUpdate], RoleFinder.project)
def update_card_attachment(
    project_uid: str,
    card_uid: str,
    attachment_uid: str,
    user: User,
    service: DomainService,
    name: str | None = None,
    order: int | None = None,
) -> dict[str, Any]:
    """Update native attachment metadata after full field validation."""

    return update_attachment(_adapter(user, service), project_uid, card_uid, attachment_uid, name, order)


@McpTool.add("user", description="Delete a card attachment without exposing file bytes.")
@McpRoleFilter.add(ProjectRole, [ProjectRoleAction.CardUpdate], RoleFinder.project)
def delete_card_attachment(
    project_uid: str,
    card_uid: str,
    attachment_uid: str,
    user: User,
    service: DomainService,
) -> dict[str, bool]:
    """Delete a native card attachment after ancestry validation."""

    return delete_attachment(_adapter(user, service), project_uid, card_uid, attachment_uid)


@McpTool.add(description="List bounded public card metadata; reserved and secret-like keys are hidden.")
@McpRoleFilter.add(ProjectRole, [ProjectRoleAction.Read], RoleFinder.project)
def get_public_card_metadata(
    project_uid: str,
    card_uid: str,
    user_or_bot: User | Bot,
    service: DomainService,
    limit: int = 20,
    cursor: str | None = None,
) -> BoundedItemsDto:
    """Read public metadata only."""

    return query_public_metadata(_adapter(user_or_bot, service), project_uid, card_uid, limit, cursor)


@McpTool.add(description="Read one public card metadata entry by key.")
@McpRoleFilter.add(ProjectRole, [ProjectRoleAction.Read], RoleFinder.project)
def get_public_card_metadata_by_key(
    project_uid: str,
    card_uid: str,
    key: str,
    user_or_bot: User | Bot,
    service: DomainService,
) -> dict[str, Any]:
    """Read one explicitly public metadata entry."""

    return query_public_metadata_key(_adapter(user_or_bot, service), project_uid, card_uid, key)


@McpTool.add(description="Save one public card metadata entry; secret-like keys are rejected.")
@McpRoleFilter.add(ProjectRole, [ProjectRoleAction.CardUpdate], RoleFinder.project)
def save_public_card_metadata(
    project_uid: str,
    card_uid: str,
    key: str,
    value: str,
    user_or_bot: User | Bot,
    service: DomainService,
    old_key: str | None = None,
) -> dict[str, Any]:
    """Create, update, or rename public metadata."""

    return save_public_metadata(_adapter(user_or_bot, service), project_uid, card_uid, key, value, old_key)


@McpTool.add(description="Delete public card metadata keys; reserved keys are rejected.")
@McpRoleFilter.add(ProjectRole, [ProjectRoleAction.CardUpdate], RoleFinder.project)
def delete_public_card_metadata(
    project_uid: str,
    card_uid: str,
    keys: list[str],
    user_or_bot: User | Bot,
    service: DomainService,
) -> dict[str, bool]:
    """Delete one or more explicitly public metadata entries."""

    return delete_public_metadata(_adapter(user_or_bot, service), project_uid, card_uid, keys)
