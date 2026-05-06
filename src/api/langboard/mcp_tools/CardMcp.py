import base64
import io
from langboard_shared.core.db import EditorContentModel
from langboard_shared.core.storage import Storage, StorageName
from langboard_shared.core.types import SafeDateTime
from langboard_shared.core.utils.Converter import convert_python_data
from langboard_shared.domain.models import Bot, Card, CardMetadata, Project, ProjectRole, User
from langboard_shared.domain.models.bases import ALL_GRANTED
from langboard_shared.domain.models.ProjectRole import ProjectRoleAction
from langboard_shared.domain.services.DomainService import DomainService
from langboard_shared.helpers import InfraHelper
from langboard_shared.security import RoleFinder
from ..mcp_integration import McpRoleFilter, McpTool


@McpTool.add(description="Get all cards in a project.")
@McpRoleFilter.add(ProjectRole, [ProjectRoleAction.Read], RoleFinder.project)
def get_cards(project_uid: str, service: DomainService) -> dict:
    project = service.project.get_by_id_like(project_uid)
    if not project:
        raise ValueError("Project not found")
    cards = service.card.get_api_list_by_project(project)
    return {"cards": cards}


def _issue_card_metadata_matches(metadata: dict, title: str) -> bool:
    normalized_title = title.lower()
    if any(
        str(metadata.get(key) or "").lower() in {"issue", "bug", "task", "ui_selector_issue"}
        for key in ("kind", "type", "card_type", "work_item_kind")
    ):
        return True
    if str(metadata.get("source_type") or "").lower() in {"element_selector", "ui_selector", "playwright_selector"}:
        return True
    return normalized_title.startswith(("issue:", "bug:")) or "[issue]" in normalized_title


@McpTool.add(description="Get issue cards in a project, optionally filtered by column, metadata, and title text.")
@McpRoleFilter.add(ProjectRole, [ProjectRoleAction.Read], RoleFinder.project)
def get_issue_cards(
    project_uid: str,
    service: DomainService,
    column_uid: str | None = None,
    metadata_key: str | None = None,
    metadata_value: str | None = None,
    title_contains: str | None = None,
    include_metadata: bool = True,
) -> dict:
    project = service.project.get_by_id_like(project_uid)
    if not project:
        raise ValueError("Project not found")

    normalized_column_uid = (column_uid or "").strip()
    normalized_metadata_key = (metadata_key or "").strip()
    normalized_metadata_value = (metadata_value or "").strip()
    normalized_title = (title_contains or "").strip().lower()
    cards = []
    for card in service.card.get_api_list_by_project(project):
        if normalized_column_uid and card.get("project_column_uid") != normalized_column_uid:
            continue
        if normalized_title and normalized_title not in str(card.get("title") or "").lower():
            continue

        card_model = service.card.get_by_id_like(card.get("uid"))
        if not card_model:
            continue
        metadata = service.metadata.get_all_as_api(CardMetadata, card_model, as_dict=True)
        if normalized_metadata_key:
            if normalized_metadata_key not in metadata:
                continue
            if (
                normalized_metadata_value
                and str(metadata.get(normalized_metadata_key) or "") != normalized_metadata_value
            ):
                continue
        elif not _issue_card_metadata_matches(metadata, str(card.get("title") or "")):
            continue

        if include_metadata:
            card = {**card, "metadata": metadata}
        cards.append(card)

    return {"cards": cards, "count": len(cards)}


@McpTool.add(description="Create an issue card from a UI selector or delivery issue.")
@McpRoleFilter.add(ProjectRole, [ProjectRoleAction.CardUpdate], RoleFinder.project)
def create_issue_card(
    project_uid: str,
    column_uid: str,
    title: str,
    description: str | None,
    user_or_bot: User | Bot,
    service: DomainService,
    selector: str | None = None,
    route: str | None = None,
    source_type: str = "element_selector",
    severity: str = "",
) -> dict:
    result = service.card.create(
        user_or_bot,
        project_uid,
        column_uid,
        title,
        EditorContentModel(content=description or ""),
        None,
    )
    if not result:
        raise ValueError("Failed to create")
    _, api_card = result
    card_uid = api_card.get("uid")
    card = service.card.get_by_id_like(card_uid)
    if not card:
        return api_card
    metadata = {
        "kind": "issue",
        "work_item_kind": "ui_selector_issue",
        "source_type": source_type or "element_selector",
        "selector": selector or "",
        "route": route or "",
        "severity": severity or "",
    }
    for key, value in metadata.items():
        if value:
            service.metadata.save(CardMetadata, card, key, str(value), None)
    return {**api_card, "metadata": metadata}


@McpTool.add(description="Get card details.")
@McpRoleFilter.add(ProjectRole, [ProjectRoleAction.Read], RoleFinder.project)
def get_card(project_uid: str, card_uid: str, service: DomainService) -> dict:
    params = InfraHelper.get_records_with_foreign_by_params((Project, project_uid), (Card, card_uid))
    if not params:
        raise ValueError("Card not found")
    project, card = params
    api_card = service.card.get_details(project, card)
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
    api_card = service.card.get_details(project, card)
    if not api_card:
        raise ValueError("Card not found")
    bot_scopes = []
    can_set = isinstance(user_or_bot, Bot)
    if isinstance(user_or_bot, User):
        actions = service.project.get_user_role_actions_by_project(user_or_bot, project)
        can_set = ALL_GRANTED in actions or ProjectRoleAction.Update.value in actions
    if can_set:
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
    title: str | None,
    description: str | None,
    deadline_at: str | None,
    user_or_bot: User | Bot,
    service: DomainService,
) -> dict:
    form_dict = {}
    if title is not None:
        form_dict["title"] = title
    if description is not None:
        form_dict["description"] = EditorContentModel(content=description)
    if deadline_at is not None:
        if deadline_at:
            val = SafeDateTime.fromisoformat(deadline_at)
            if val.tzinfo is None:
                val = val.replace(tzinfo=SafeDateTime.now().astimezone().tzinfo)
            form_dict["deadline_at"] = val
        else:
            form_dict["deadline_at"] = None
    result = service.card.update(user_or_bot, project_uid, card_uid, form_dict)
    if not result:
        raise ValueError("Failed to update")
    if result is True:
        response = {}
        if title is not None:
            response["title"] = title
        if description is not None:
            response["description"] = convert_python_data(EditorContentModel(content=description))
        if deadline_at is not None:
            response["deadline_at"] = deadline_at
        return response
    return result


@McpTool.add(description="Archive a card.")
@McpRoleFilter.add(ProjectRole, [ProjectRoleAction.CardUpdate], RoleFinder.project)
def archive_card(project_uid: str, card_uid: str, user_or_bot: User | Bot, service: DomainService) -> dict:
    p = service.project.get_by_id_like(project_uid)
    if not p:
        raise ValueError("Project not found")
    result = service.card.archive(user_or_bot, p, card_uid)
    if not result:
        raise ValueError("Failed to archive")
    return {"message": "Archived"}


@McpTool.add(description="Delete a card. (Only available for archived cards)")
@McpRoleFilter.add(ProjectRole, [ProjectRoleAction.CardDelete], RoleFinder.project)
def delete_card(project_uid: str, card_uid: str, user_or_bot: User | Bot, service: DomainService) -> dict:
    result = service.card.delete(user_or_bot, project_uid, card_uid)
    if not result:
        raise ValueError("Failed to delete")
    return {"message": "Deleted"}


@McpTool.add(description="Change card order or move to another project column.")
@McpRoleFilter.add(ProjectRole, [ProjectRoleAction.CardUpdate], RoleFinder.project)
def change_card_order_or_move_column(
    project_uid: str, card_uid: str, order: int, column_uid: str | None, user_or_bot: User | Bot, service: DomainService
) -> dict:
    result = service.card.change_order(user_or_bot, project_uid, card_uid, order, column_uid or "")
    if not result:
        raise ValueError("Failed to change order or move column")
    return {"message": "Order changed or card moved"}


@McpTool.add("user", description="Upload a card attachment. Accepts base64 encoded file data.")
@McpRoleFilter.add(ProjectRole, [ProjectRoleAction.Read], RoleFinder.project)
def upload_card_attachment(
    project_uid: str,
    card_uid: str,
    filename: str,
    file_data_base64: str,
    user: User,
    service: DomainService,
) -> dict:
    try:
        file_content = base64.b64decode(file_data_base64)
    except Exception as e:
        raise ValueError(f"Invalid base64 data: {str(e)}")

    file_object = io.BytesIO(file_content)
    file_object.name = filename

    file_model = Storage.upload(file_object, StorageName.CardAttachment)
    if not file_model:
        raise ValueError("Failed to upload file")

    result = service.card_attachment.create(user, project_uid, card_uid, file_model)
    if not result:
        raise ValueError("Failed to create attachment")

    return result.api_response()
