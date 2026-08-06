import base64
import io
from langboard_shared.core.db import EditorContentModel
from langboard_shared.core.storage import Storage, StorageName
from langboard_shared.core.types import SafeDateTime
from langboard_shared.core.utils.Converter import convert_python_data
from langboard_shared.domain.models import Bot, Card, Project, ProjectRole, User
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
