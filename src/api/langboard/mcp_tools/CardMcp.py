"""MCP tools for project cards, from service-backed operations to the safe native card workspace."""

import base64
import io
from binascii import Error as Base64Error
from typing import Annotated, Any, Literal
from fastmcp.exceptions import ValidationError
from langboard_shared.core.db import EditorContentModel
from langboard_shared.core.exceptions.CardDeleteForbidden import CardDeleteForbidden
from langboard_shared.core.storage import Storage, StorageName
from langboard_shared.core.types import SafeDateTime
from langboard_shared.core.utils.Converter import convert_python_data
from langboard_shared.domain.models import Bot, Card, Project, ProjectRole, User
from langboard_shared.domain.models.bases import ALL_GRANTED
from langboard_shared.domain.models.ProjectRole import ProjectRoleAction
from langboard_shared.domain.services.DomainService import DomainService
from langboard_shared.Env import Env
from langboard_shared.helpers import InfraHelper
from langboard_shared.security import RoleFinder
from pydantic import BeforeValidator
from ..card_workspace.application import (
    CardBundleResponse,
    ProjectCardListResponse,
    ProjectIdentityResponse,
)
from ..card_workspace.application import apply_card_graph_patch as apply_graph_patch
from ..card_workspace.application import cardify_card_checkitem as cardify_checkitem
from ..card_workspace.application import create_card_checkitem as create_checkitem
from ..card_workspace.application import create_card_checklist as create_checklist
from ..card_workspace.application import create_card_in_leftmost_column as create_leftmost
from ..card_workspace.application import delete_card_attachment as delete_attachment
from ..card_workspace.application import delete_card_checkitem as delete_checkitem
from ..card_workspace.application import delete_card_checklist as delete_checklist
from ..card_workspace.application import delete_public_card_metadata as delete_public_metadata
from ..card_workspace.application import get_card_bundle as query_card_bundle
from ..card_workspace.application import get_project_identity as query_project_identity
from ..card_workspace.application import get_public_card_metadata as query_public_metadata
from ..card_workspace.application import get_public_card_metadata_by_key as query_public_metadata_key
from ..card_workspace.application import list_project_cards as query_project_cards
from ..card_workspace.application import patch_card_description as replace_description_text
from ..card_workspace.application import provision_project as provision
from ..card_workspace.application import reconcile_card_checklist_projection as reconcile_checklist
from ..card_workspace.application import replace_card_description as replace_description
from ..card_workspace.application import save_public_card_metadata as save_public_metadata
from ..card_workspace.application import set_card_people_and_labels as replace_people_and_labels
from ..card_workspace.application import set_card_relationships as replace_relationships
from ..card_workspace.application import update_card_attachment as update_attachment
from ..card_workspace.application import update_card_checkitem as update_checkitem
from ..card_workspace.application import update_card_checklist as update_checklist
from ..card_workspace.application.dtos import BoundedItemsDto
from ..card_workspace.application.projections import public_comment
from ..card_workspace.domain import (
    CardBundleInclude,
    CardGraphEdge,
    CardGraphNewCard,
    ChecklistProjectionItem,
    CommentPage,
    DescriptionPatchConflict,
    ExactTextReplacement,
    SectionPage,
)
from ..card_workspace.infrastructure import NativeCardWorkspaceAdapter
from ..mcp_integration import McpRoleFilter, McpTool


def _get_card_in_project(project_uid: str, card_uid: str) -> tuple[Project, Card] | None:
    return InfraHelper.get_records_with_foreign_by_params((Project, project_uid), (Card, card_uid))


def _require_task_card(project_uid: str, card_uid: str) -> tuple[Project, Card]:
    params = _get_card_in_project(project_uid, card_uid)
    if not params:
        raise ValueError("Card not found")
    if params[1].is_linked_resource:
        raise ValueError("Linked Wiki cards are read-only references; move or remove the card, or edit the source Wiki")
    return params


@McpTool.add(description="Get all cards in a project.")
@McpRoleFilter.add(ProjectRole, [ProjectRoleAction.Read], RoleFinder.project)
def get_cards(project_uid: str, user_or_bot: User | Bot, service: DomainService) -> dict:
    project = service.project.get_by_id_like(project_uid)
    if not project:
        raise ValueError("Project not found")
    cards = service.card.get_api_list_by_project(project, user_or_bot)
    return {"cards": cards}


@McpTool.add(description="Get card details.")
@McpRoleFilter.add(ProjectRole, [ProjectRoleAction.Read], RoleFinder.project)
def get_card(project_uid: str, card_uid: str, user_or_bot: User | Bot, service: DomainService) -> dict:
    params = _get_card_in_project(project_uid, card_uid)
    if not params:
        raise ValueError("Card not found")
    project, card = params
    api_card = service.card.get_details(project, card, user_or_bot)
    if not api_card:
        raise ValueError("Card not found")
    return api_card


@McpTool.add(description="Get card checklists.")
@McpRoleFilter.add(ProjectRole, [ProjectRoleAction.Read], RoleFinder.project)
def get_card_checklists(project_uid: str, card_uid: str, service: DomainService) -> dict:
    params = InfraHelper.get_records_with_foreign_by_params((Project, project_uid), (Card, card_uid))
    if not params:
        raise ValueError("Card not found")
    _, card = params
    checklists = service.checklist.get_api_list_by_card(card)
    return {"checklists": checklists}


@McpTool.add(description="Get card attachments.")
@McpRoleFilter.add(ProjectRole, [ProjectRoleAction.Read], RoleFinder.project)
def get_card_attachments(project_uid: str, card_uid: str, service: DomainService) -> dict:
    params = InfraHelper.get_records_with_foreign_by_params((Project, project_uid), (Card, card_uid))
    if not params:
        raise ValueError("Card not found")
    _, card = params
    attachments = service.card_attachment.get_api_list_by_card(card)
    return {"attachments": attachments}


@McpTool.add(description="Get bot scopes for a card.")
@McpRoleFilter.add(ProjectRole, [ProjectRoleAction.Read], RoleFinder.project)
def get_card_bot_scopes(project_uid: str, card_uid: str, user_or_bot: User | Bot, service: DomainService) -> dict:
    params = InfraHelper.get_records_with_foreign_by_params((Project, project_uid), (Card, card_uid))
    if not params:
        raise ValueError("Card not found")
    project, card = params
    api_card = service.card.get_details(project, card, user_or_bot)
    if not api_card:
        raise ValueError("Card not found")
    bot_scopes = []
    can_set = isinstance(user_or_bot, Bot)
    if isinstance(user_or_bot, User):
        actions = service.project.get_user_role_actions_by_project(user_or_bot, project)
        can_set = ALL_GRANTED in actions or ProjectRoleAction.Update.value in actions
    if can_set and not card.is_linked_resource:
        bot_scopes = service.card.get_api_bot_scope_list(project, card)
    return {"bot_scopes": bot_scopes}


@McpTool.add(description="Create a card.")
@McpRoleFilter.add(ProjectRole, [ProjectRoleAction.CardUpdate], RoleFinder.project)
def create_card(
    project_uid: str,
    column_uid: str,
    title: str,
    description: str | None,
    assign_user_uids: list[str] | None,
    user_or_bot: User | Bot,
    service: DomainService,
) -> dict:
    description_model = EditorContentModel(content=description or "")
    result = service.card.create(user_or_bot, project_uid, column_uid, title, description_model, assign_user_uids)
    if not result:
        raise ValueError("Failed to create")
    _, api_card = result
    return api_card


@McpTool.add(description="Change card details.")
@McpRoleFilter.add(ProjectRole, [ProjectRoleAction.CardUpdate], RoleFinder.project)
def change_card_details(
    project_uid: str,
    card_uid: str,
    user_or_bot: User | Bot,
    service: DomainService,
    title: str | None = None,
    description: str | None = None,
    deadline_at: str | None = None,
) -> dict:
    if title is None and description is None and deadline_at is None:
        raise ValueError("At least one card detail field is required")
    normalized_title = None
    if title is not None:
        normalized_title = title.strip()
        if not normalized_title:
            raise ValueError("Card title is required")
    parsed_deadline = None
    if deadline_at:
        parsed_deadline = SafeDateTime.fromisoformat(deadline_at)
        if parsed_deadline.tzinfo is None:
            parsed_deadline = parsed_deadline.replace(tzinfo=SafeDateTime.now().astimezone().tzinfo)

    form_dict = {}
    if normalized_title is not None:
        form_dict["title"] = normalized_title
    if description is not None:
        form_dict["description"] = EditorContentModel(content=description)
    if deadline_at is not None:
        form_dict["deadline_at"] = parsed_deadline
    _require_task_card(project_uid, card_uid)
    result = service.card.update(user_or_bot, project_uid, card_uid, form_dict)
    if not result:
        raise ValueError("Failed to update")
    if result is True:
        response = {}
        if normalized_title is not None:
            response["title"] = normalized_title
        if description is not None:
            response["description"] = convert_python_data(EditorContentModel(content=description))
        if deadline_at is not None:
            response["deadline_at"] = deadline_at
        return response
    return result


@McpTool.add(description="Archive a card.")
@McpRoleFilter.add(ProjectRole, [ProjectRoleAction.CardUpdate], RoleFinder.project)
def archive_card(project_uid: str, card_uid: str, user_or_bot: User | Bot, service: DomainService) -> dict:
    params = _get_card_in_project(project_uid, card_uid)
    if not params:
        raise ValueError("Card not found")
    project, card = params
    result = service.card.archive(user_or_bot, project, card)
    if not result:
        raise ValueError("Failed to archive")
    return {"message": "Removed from board" if card.is_linked_resource else "Archived"}


@McpTool.add(description="Delete an archived card when the signed-in actor is its original author or an administrator.")
@McpRoleFilter.add(ProjectRole, [ProjectRoleAction.CardDelete], RoleFinder.project)
def delete_card(project_uid: str, card_uid: str, user_or_bot: User | Bot, service: DomainService) -> dict:
    try:
        result = service.card.delete(user_or_bot, project_uid, card_uid)
    except CardDeleteForbidden as exc:
        raise ValidationError(f"{exc.code}: {exc}") from exc
    if not result:
        raise ValueError("Failed to delete")
    return {"message": "Deleted"}


@McpTool.add(description="Change card order or move to another project column.")
@McpRoleFilter.add(ProjectRole, [ProjectRoleAction.CardUpdate], RoleFinder.project)
def change_card_order_or_move_column(
    project_uid: str,
    card_uid: str,
    order: int,
    user_or_bot: User | Bot,
    service: DomainService,
    column_uid: str | None = None,
) -> dict:
    if isinstance(order, bool) or order < 0:
        raise ValueError("Card order must be a non-negative integer")
    normalized_column_uid = None
    if column_uid is not None:
        normalized_column_uid = column_uid.strip()
        if not normalized_column_uid:
            raise ValueError("column_uid cannot be blank")
    result = service.card.change_order(user_or_bot, project_uid, card_uid, order, normalized_column_uid or "")
    if not result:
        raise ValueError("Failed to change order or move column")
    return {"message": "Order changed or card moved"}


@McpTool.add("user", description="Upload a card attachment. Accepts base64 encoded file data.")
@McpRoleFilter.add(ProjectRole, [ProjectRoleAction.CardUpdate], RoleFinder.project)
def upload_card_attachment(
    project_uid: str,
    card_uid: str,
    filename: str,
    file_data_base64: str,
    user: User,
    service: DomainService,
) -> dict:
    _require_task_card(project_uid, card_uid)
    max_file_bytes = Env.MAX_FILE_SIZE_MB * 1024 * 1024
    max_base64_length = ((max_file_bytes + 2) // 3) * 4
    if len(file_data_base64) > max_base64_length:
        raise ValueError(f"Attachment exceeds the {Env.MAX_FILE_SIZE_MB} MB upload limit")

    try:
        file_content = base64.b64decode(file_data_base64, validate=True)
    except (Base64Error, ValueError) as e:
        raise ValueError(f"Invalid base64 data: {str(e)}")

    if len(file_content) > max_file_bytes:
        raise ValueError(f"Attachment exceeds the {Env.MAX_FILE_SIZE_MB} MB upload limit")

    file_object = io.BytesIO(file_content)
    file_object.name = filename

    file_model = Storage.upload(file_object, StorageName.CardAttachment)
    if not file_model:
        raise ValueError("Failed to upload file")

    result = service.card_attachment.create(user, project_uid, card_uid, file_model)
    if not result:
        raise ValueError("Failed to create attachment")

    return result.api_response()


# ---------------------------------------------------------------------------
# Safe native card workspace tools
# ---------------------------------------------------------------------------


@McpTool.add("user", description="Assign the authenticated user to this card, preserving every existing assignee.")
@McpRoleFilter.add(ProjectRole, [ProjectRoleAction.CardUpdate], RoleFinder.project)
def assign_card_to_me(project_uid: str, card_uid: str, user: User, service: DomainService) -> dict[str, Any]:
    """Use the server-authenticated identity, never a caller-supplied user UID."""
    try:
        return service.card.assign_self(user, project_uid, card_uid)
    except ValueError as exc:
        raise ValidationError(
            f"{exc}. No assignment was made. Ask a project updater to onboard you as a member, then retry once."
        ) from exc


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


def _as_exact_text_replacement(
    value: dict[str, Any] | ExactTextReplacement,
) -> ExactTextReplacement:
    """Parse one transport edit into the immutable domain value."""

    return value if isinstance(value, ExactTextReplacement) else ExactTextReplacement(**value)


JsonExactTextReplacement = Annotated[
    ExactTextReplacement,
    BeforeValidator(_as_exact_text_replacement),
]


def _adapter(actor: User | Bot, service: DomainService) -> NativeCardWorkspaceAdapter:
    """Build the native adapter at the MCP composition root."""

    return NativeCardWorkspaceAdapter(actor, service)


@McpTool.add(
    "user",
    description="Provision a new project with its standard workflow from a named template, or the configured default.",
)
def provision_project(
    title: str,
    user: User,
    service: DomainService,
    description: str | None = None,
    template_name: str | None = None,
    infer_template_prefix: bool = False,
) -> dict[str, Any]:
    """Provision a template-backed project with its kanban workflow columns."""

    return provision(
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
        "Read compact card core, public creator identity, and workflow fields. Request description, people, classification, checklists, "
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
    items = []
    for member in members[:50]:
        fields = ("uid", "username")
        # Invitation placeholders store an email in firstname; expose names only for real users.
        if member.get("type") == User.USER_TYPE:
            fields += ("firstname", "lastname")
        items.append({key: member[key] for key in fields if key in member})
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


@McpTool.add(
    description=(
        "Atomically apply one or more exact edits to Plate-compatible Markdown. Pass edits for a multi-hunk patch, "
        "or old_text/new_text for backwards compatibility. Fails without writing when the revision or any reviewed "
        "fragment is stale or ambiguous."
    )
)
@McpRoleFilter.add(ProjectRole, [ProjectRoleAction.CardUpdate], RoleFinder.project)
def patch_card_description(
    project_uid: str,
    card_uid: str,
    user_or_bot: User | Bot,
    service: DomainService,
    old_text: str | None = None,
    new_text: str | None = None,
    edits: list[JsonExactTextReplacement] | None = None,
    expected_revision: str | None = None,
) -> dict[str, Any]:
    """Conditionally apply one approved Markdown patch."""

    if edits is not None:
        if old_text is not None or new_text is not None:
            raise ValueError("Pass either edits or old_text/new_text, not both")
        replacements = edits
    else:
        if old_text is None or new_text is None:
            raise ValueError("old_text and new_text are required when edits is omitted")
        replacements = [ExactTextReplacement(old_text=old_text, new_text=new_text)]

    try:
        return replace_description_text(
            _adapter(user_or_bot, service),
            project_uid,
            card_uid,
            replacements,
            expected_revision,
        )
    except DescriptionPatchConflict as exc:
        raise ValidationError(f"{exc}. No changes saved; read the description and review a new patch.") from exc


@McpTool.add(description="Replace a complete card description after reviewing its current revision.")
@McpRoleFilter.add(ProjectRole, [ProjectRoleAction.CardUpdate], RoleFinder.project)
def replace_card_description(
    project_uid: str,
    card_uid: str,
    description: str,
    expected_revision: str,
    user_or_bot: User | Bot,
    service: DomainService,
) -> dict[str, Any]:
    """Safely initialize, clear, or replace the complete Markdown body."""

    try:
        return replace_description(
            _adapter(user_or_bot, service), project_uid, card_uid, description, expected_revision
        )
    except DescriptionPatchConflict as exc:
        raise ValidationError(f"{exc}. No changes saved; read the description and review the replacement.") from exc


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

    if not isinstance(content, str) or not content.strip():
        raise ValueError("Comment is required")
    comment = service.card_comment.create(
        user_or_bot, project_uid, card_uid, EditorContentModel(content=content.strip())
    )
    if comment is None:
        raise ValueError("Card not found in project")
    return {"comment": public_comment(comment.api_response())}


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

    if not isinstance(content, str) or not content.strip():
        raise ValueError("Comment is required")
    comment = service.card_comment.update(
        user_or_bot, project_uid, card_uid, comment_uid, EditorContentModel(content=content.strip())
    )
    if comment is None:
        raise PermissionError("Comment not found or not owned by current actor")
    return {"comment": public_comment(comment.api_response())}


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

    if not service.card_comment.delete(user_or_bot, project_uid, card_uid, comment_uid):
        raise PermissionError("Comment not found or not owned by current actor")
    return {"deleted": True}


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
        "Create a card from one existing checkitem in an explicit active project column. "
        "The checkitem remains linked to the resulting card."
    )
)
@McpRoleFilter.add(ProjectRole, [ProjectRoleAction.CardUpdate], RoleFinder.project)
def cardify_card_checkitem(
    project_uid: str,
    card_uid: str,
    checkitem_uid: str,
    project_column_uid: str,
    user_or_bot: User | Bot,
    service: DomainService,
) -> dict[str, Any]:
    """Promote one native checkitem to a linked card."""

    return cardify_checkitem(
        _adapter(user_or_bot, service),
        project_uid,
        card_uid,
        checkitem_uid,
        project_column_uid,
    )


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


@McpTool.add(
    description=(
        "Create a structured content block on a card. block_type must be "
        "'code' (payload: language, source, optional title) or 'diagram' "
        "(payload: engine mermaid|plantuml|graphviz|flowchart, source, "
        "optional view_mode source|rendered|both) or 'rich_text' (payload: text). "
        "No Markdown delimiters are needed."
    )
)
@McpRoleFilter.add(ProjectRole, [ProjectRoleAction.CardUpdate], RoleFinder.project)
def create_card_content_block(
    project_uid: str,
    card_uid: str,
    block_type: str,
    payload: dict[str, Any],
    order: int | None = None,
    after_block_uid: str | None = None,
    user_or_bot: User | Bot = None,
    service: DomainService = None,
) -> dict[str, Any]:
    """Create one typed content block anchored to a card."""

    if block_type not in ("rich_text", "code", "diagram"):
        raise ValueError("block_type must be rich_text, code or diagram")
    block = service.card_content_block.create(
        user_or_bot, project_uid, card_uid, block_type, payload, order, after_block_uid
    )
    if block is None:
        raise ValueError("Card not found in project")
    return {"content_block": _public_content_block(block)}


@McpTool.add(
    description=(
        "Partially update a card content block. Requires the block's current "
        "revision for optimistic locking; a mismatch fails with a conflict error."
    )
)
@McpRoleFilter.add(ProjectRole, [ProjectRoleAction.CardUpdate], RoleFinder.project)
def update_card_content_block(
    project_uid: str,
    card_uid: str,
    block_uid: str,
    expected_revision: int,
    payload: dict[str, Any],
    user_or_bot: User | Bot = None,
    service: DomainService = None,
) -> dict[str, Any]:
    """Update one content block under optimistic locking."""

    if expected_revision < 1:
        raise ValueError("expected_revision must be positive")
    block = service.card_content_block.update(user_or_bot, project_uid, card_uid, block_uid, expected_revision, payload)
    if block is None:
        raise PermissionError("Block not found in card")
    return {"content_block": _public_content_block(block)}


@McpTool.add(description="Delete a card content block by uid.")
@McpRoleFilter.add(ProjectRole, [ProjectRoleAction.CardUpdate], RoleFinder.project)
def delete_card_content_block(
    project_uid: str,
    card_uid: str,
    block_uid: str,
    user_or_bot: User | Bot = None,
    service: DomainService = None,
) -> dict[str, bool]:
    """Delete one content block after project-card-block validation."""

    if not service.card_content_block.delete(user_or_bot, project_uid, card_uid, block_uid):
        raise PermissionError("Block not found in card")
    return {"deleted": True}


@McpTool.add(description="Reposition a card content block using after_block_uid or an explicit order (not both).")
@McpRoleFilter.add(ProjectRole, [ProjectRoleAction.CardUpdate], RoleFinder.project)
def move_card_content_block(
    project_uid: str,
    card_uid: str,
    block_uid: str,
    after_block_uid: str | None = None,
    order: int | None = None,
    user_or_bot: User | Bot = None,
    service: DomainService = None,
) -> dict[str, bool]:
    """Move one content block within its card."""

    if after_block_uid is not None and order is not None:
        raise ValueError("pass either after_block_uid or order, not both")
    if not service.card_content_block.move(user_or_bot, project_uid, card_uid, block_uid, after_block_uid, order):
        raise PermissionError("Block not found in card")
    return {"moved": True}


def _public_content_block(block: Any) -> dict[str, Any]:
    return {
        "block_uid": block.get_uid(),
        "type": block.block_type,
        "order": block.order,
        "revision": block.revision,
        "payload": block.payload,
        "updated_at": block.updated_at.isoformat() if block.updated_at else None,
    }
