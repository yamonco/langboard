from fastapi import status
from langboard_shared.core.db import EditorContentModel
from langboard_shared.core.filter import AuthFilter
from langboard_shared.core.routing import (
    ApiErrorCode,
    ApiException,
    ApiPermission,
    AppRouter,
    EEditorCollaborationType,
    JsonResponse,
    collaborative_block,
    collaborative_edit,
    collaborative_rich,
    collaborative_text,
    create_editor_collaboration_document_id,
)
from langboard_shared.core.schema import OpenApiSchema
from langboard_shared.core.types import SafeDateTime
from langboard_shared.core.utils.Converter import convert_python_data
from langboard_shared.domain.models import (
    Bot,
    Card,
    CardAttachment,
    CardBotScope,
    CardComment,
    CardRelationship,
    Checkitem,
    Checklist,
    GlobalCardRelationshipType,
    Project,
    ProjectColumn,
    ProjectLabel,
    ProjectRole,
    User,
)
from langboard_shared.domain.models.bases import ALL_GRANTED
from langboard_shared.domain.models.ProjectRole import ProjectRoleAction
from langboard_shared.domain.services import DomainService
from langboard_shared.filter import RoleFilter
from langboard_shared.helpers import InfraHelper
from langboard_shared.security import Auth, RoleFinder
from .forms import (
    AssignUsersForm,
    ChangeCardDetailsForm,
    ChangeChildOrderForm,
    CreateCardForm,
    UpdateCardLabelsForm,
    UpdateCardRelationshipsForm,
)


@AppRouter.schema(permission=ApiPermission.Read)
@AppRouter.api.get(
    "/board/{project_uid}/card/{card_uid}",
    tags=["Board.Card"],
    description="Get card details.",
    responses=(
        OpenApiSchema()
        .suc(
            {
                "card": (
                    Card,
                    {
                        "schema": {
                            "project_column_name": "string",
                            "count_comment": "integer",
                            "project_members": [User],
                            "labels": [ProjectLabel],
                            "member_uids": "string[]",
                            "relationships": [CardRelationship],
                            "current_auth_role_actions": [ALL_GRANTED, ProjectRoleAction],
                        }
                    },
                ),
                "checklists": [
                    (
                        Checklist,
                        {
                            "schema": {
                                "checkitems": [
                                    (
                                        Checkitem,
                                        {
                                            "schema": {
                                                "card_uid": "string",
                                                "timer_started_at?": "string",
                                                "cardified_card?": "string",
                                                "user?": User,
                                            }
                                        },
                                    ),
                                ]
                            }
                        },
                    ),
                ],
                "attachments": [CardAttachment],
                "global_relationships": [GlobalCardRelationshipType],
                "project_columns": [(ProjectColumn, {"schema": {"count": "integer"}})],
                "project_labels": [ProjectLabel],
                "bot_scopes": [CardBotScope],
            }
        )
        .auth()
        .forbidden()
        .err(404, ApiErrorCode.NF2003)
        .get()
    ),
)
@RoleFilter.add(ProjectRole, [ProjectRoleAction.Read], RoleFinder.project)
@AuthFilter.add()
def get_card_details(
    project_uid: str,
    card_uid: str,
    user_or_bot: User | Bot = Auth.scope("all"),
    service: DomainService = DomainService.scope(),
) -> JsonResponse:
    params = InfraHelper.get_records_with_foreign_by_params((Project, project_uid), (Card, card_uid))
    if not params:
        raise ApiException.NotFound_404(ApiErrorCode.NF2003)
    project, card = params
    api_card = service.card.get_details(project, card)
    if api_card is None:
        raise ApiException.NotFound_404(ApiErrorCode.NF2003)
    global_relationships = service.app_setting.get_api_global_relationship_list()
    bot_scopes = []
    can_set_scopes = isinstance(user_or_bot, Bot)
    if isinstance(user_or_bot, User):
        actions = service.project.get_user_role_actions_by_project(user_or_bot, project)
        api_card["current_auth_role_actions"] = actions
        can_set_scopes = ALL_GRANTED in actions or ProjectRoleAction.Update.value in actions
    if can_set_scopes:
        bot_scopes = service.card.get_api_bot_scope_list(project, card)

    project_columns = service.project_column.get_api_list_by_project(project.id)
    project_labels = service.project_label.get_api_list_by_project(project)

    checklists = service.checklist.get_api_list_by_card(card)
    attachments = service.card_attachment.get_api_list_by_card(card)

    return JsonResponse(
        content={
            "card": api_card,
            "checklists": checklists,
            "attachments": attachments,
            "global_relationships": global_relationships,
            "project_columns": project_columns,
            "project_labels": project_labels,
            "bot_scopes": bot_scopes,
        }
    )


@AppRouter.schema(permission=ApiPermission.Read)
@AppRouter.api.get(
    "/board/{project_uid}/card/{card_uid}/comments",
    tags=["Board.Card"],
    description="Get card comments.",
    responses=(
        OpenApiSchema()
        .suc(
            {
                "comments": [
                    (
                        CardComment,
                        {
                            "schema": {
                                "user?": User,
                                "bot?": Bot,
                                "reactions": {"<reaction type>": ["<user or bot uid>"]},
                            }
                        },
                    ),
                ]
            }
        )
        .auth()
        .forbidden()
        .get()
    ),
)
@RoleFilter.add(ProjectRole, [ProjectRoleAction.Read], RoleFinder.project)
@AuthFilter.add()
def get_card_comments(card_uid: str, service: DomainService = DomainService.scope()) -> JsonResponse:
    comments = service.card_comment.get_api_list_by_card(card_uid)
    return JsonResponse(content={"comments": comments})


@AppRouter.schema(form=CreateCardForm, permission=ApiPermission.Create)
@AppRouter.api.post(
    "/board/{project_uid}/card",
    tags=["Board.Card"],
    description="Create a card.",
    responses=(
        OpenApiSchema()
        .suc(
            {
                "card": (
                    Card,
                    {
                        "schema": {
                            "labels": [ProjectLabel],
                            "member_uids": "string[]",
                            "relationships": [CardRelationship],
                            "current_auth_role_actions": [ALL_GRANTED, ProjectRoleAction],
                        }
                    },
                )
            },
            201,
        )
        .auth()
        .forbidden()
        .err(404, ApiErrorCode.NF2004)
        .get()
    ),
)
@RoleFilter.add(ProjectRole, [ProjectRoleAction.CardUpdate], RoleFinder.project)
@AuthFilter.add()
def create_card(
    project_uid: str,
    form: CreateCardForm,
    user_or_bot: User | Bot = Auth.scope("all"),
    service: DomainService = DomainService.scope(),
) -> JsonResponse:
    result = service.card.create(
        user_or_bot,
        project_uid,
        form.project_column_uid,
        form.title,
        form.description,
        form.assign_users,
    )
    if not result:
        raise ApiException.NotFound_404(ApiErrorCode.NF2004)
    _, api_card = result

    return JsonResponse(content={"card": api_card}, status_code=status.HTTP_201_CREATED)


@collaborative_edit(
    collaborative_text(
        create_editor_collaboration_document_id(EEditorCollaborationType.Card, "{card_uid}", "title"), "title", "title"
    ),
    collaborative_rich(
        create_editor_collaboration_document_id(EEditorCollaborationType.Card, "{card_uid}", "description"),
        "description",
    ),
    collaborative_text(
        create_editor_collaboration_document_id(EEditorCollaborationType.Card, "{card_uid}", "deadline"),
        "deadline_at",
        "value",
    ),
)
@AppRouter.schema(form=ChangeCardDetailsForm, permission=ApiPermission.Edit)
@AppRouter.api.put(
    "/board/{project_uid}/card/{card_uid}/details",
    tags=["Board.Card"],
    description="Change card details.",
    responses=(
        OpenApiSchema()
        .suc(
            {
                "title?": "string",
                "deadline_at?": "string",
                "description?": EditorContentModel,
            }
        )
        .auth()
        .forbidden()
        .err(404, ApiErrorCode.NF2003)
        .get()
    ),
)
@RoleFilter.add(ProjectRole, [ProjectRoleAction.CardUpdate], RoleFinder.project)
@AuthFilter.add()
def change_card_details(
    project_uid: str,
    card_uid: str,
    form: ChangeCardDetailsForm,
    user_or_bot: User | Bot = Auth.scope("all"),
    service: DomainService = DomainService.scope(),
) -> JsonResponse:
    form_dict = {}
    for key in ChangeCardDetailsForm.model_fields:
        value = getattr(form, key)
        if value is None:
            continue
        elif key == "deadline_at":
            if value:
                value = SafeDateTime.fromisoformat(value)
                if value.tzinfo is None:
                    value = value.replace(tzinfo=SafeDateTime.now().astimezone().tzinfo)
            else:
                value = None
        form_dict[key] = value

    result = service.card.update(user_or_bot, project_uid, card_uid, form_dict)
    if not result:
        raise ApiException.NotFound_404(ApiErrorCode.NF2003)

    if result is True:
        response = {}
        for key in ChangeCardDetailsForm.model_fields:
            if ["title", "description", "deadline_at"].count(key) == 0:
                continue
            value = getattr(form, key)
            if value is None and key != "deadline_at":
                continue
            response[key] = convert_python_data(value)
        return JsonResponse(content=response)

    return JsonResponse(content=result)


@collaborative_edit(
    collaborative_text(
        create_editor_collaboration_document_id(EEditorCollaborationType.Card, "{card_uid}", "members"),
        "assigned_users",
        "selected-member-uids",
    )
)
@AppRouter.schema(form=AssignUsersForm, permission=ApiPermission.Edit)
@AppRouter.api.put(
    "/board/{project_uid}/card/{card_uid}/assigned-users",
    tags=["Board.Card"],
    description="Assign users to a card.",
    responses=OpenApiSchema().auth().forbidden().err(404, ApiErrorCode.NF2003).get(),
)
@RoleFilter.add(ProjectRole, [ProjectRoleAction.CardUpdate], RoleFinder.project)
@AuthFilter.add()
def update_card_assigned_users(
    project_uid: str,
    card_uid: str,
    form: AssignUsersForm,
    user_or_bot: User | Bot = Auth.scope("all"),
    service: DomainService = DomainService.scope(),
) -> JsonResponse:
    result = service.card.update_assigned_users(user_or_bot, project_uid, card_uid, form.assigned_users)
    if result is None:
        raise ApiException.NotFound_404(ApiErrorCode.NF2003)

    return JsonResponse()


@AppRouter.schema(form=ChangeChildOrderForm, permission=ApiPermission.Edit)
@AppRouter.api.put(
    "/board/{project_uid}/card/{card_uid}/order",
    tags=["Board.Card"],
    description="Change card order or move to another project column.",
    responses=OpenApiSchema().auth().forbidden().err(404, ApiErrorCode.NF2003).get(),
)
@RoleFilter.add(ProjectRole, [ProjectRoleAction.CardUpdate], RoleFinder.project)
@AuthFilter.add()
def change_card_order_or_move_column(
    project_uid: str,
    card_uid: str,
    form: ChangeChildOrderForm,
    user_or_bot: User | Bot = Auth.scope("all"),
    service: DomainService = DomainService.scope(),
) -> JsonResponse:
    result = service.card.change_order(user_or_bot, project_uid, card_uid, form.order, form.parent_uid)
    if not result:
        raise ApiException.NotFound_404(ApiErrorCode.NF2003)

    return JsonResponse()


@collaborative_edit(
    collaborative_text(
        create_editor_collaboration_document_id(EEditorCollaborationType.Card, "{card_uid}", "labels"),
        "labels",
        "selected-label-uids",
    )
)
@AppRouter.schema(form=UpdateCardLabelsForm, permission=ApiPermission.Edit)
@AppRouter.api.put(
    "/board/{project_uid}/card/{card_uid}/labels",
    tags=["Board.Card"],
    description="Update assigned labels to a card.",
    responses=OpenApiSchema().auth().forbidden().err(404, ApiErrorCode.NF2003).get(),
)
@RoleFilter.add(ProjectRole, [ProjectRoleAction.CardUpdate], RoleFinder.project)
@AuthFilter.add()
def update_card_labels(
    project_uid: str,
    card_uid: str,
    form: UpdateCardLabelsForm,
    user_or_bot: User | Bot = Auth.scope("all"),
    service: DomainService = DomainService.scope(),
) -> JsonResponse:
    result = service.card.update_labels(user_or_bot, project_uid, card_uid, form.labels)
    if not result:
        raise ApiException.NotFound_404(ApiErrorCode.NF2003)

    return JsonResponse()


@collaborative_edit(
    collaborative_text(
        create_editor_collaboration_document_id(EEditorCollaborationType.Card, "{card_uid}", "relationships-parents"),
        "relationships",
        "selected-relationships",
    ),
    collaborative_text(
        create_editor_collaboration_document_id(EEditorCollaborationType.Card, "{card_uid}", "relationships-children"),
        "relationships",
        "selected-relationships",
    ),
)
@AppRouter.schema(form=UpdateCardRelationshipsForm, permission=ApiPermission.Edit)
@AppRouter.api.put(
    "/board/{project_uid}/card/{card_uid}/relationships",
    tags=["Board.Card"],
    description="Update card relationships.",
    responses=OpenApiSchema().auth().forbidden().err(404, ApiErrorCode.NF2003).get(),
)
@RoleFilter.add(ProjectRole, [ProjectRoleAction.CardUpdate], RoleFinder.project)
@AuthFilter.add()
def update_card_relationships(
    project_uid: str,
    card_uid: str,
    form: UpdateCardRelationshipsForm,
    user_or_bot: User | Bot = Auth.scope("all"),
    service: DomainService = DomainService.scope(),
) -> JsonResponse:
    result = service.card_relationship.update(user_or_bot, project_uid, card_uid, form.is_parent, form.relationships)
    if result is None:
        raise ApiException.NotFound_404(ApiErrorCode.NF2003)

    return JsonResponse(content={"relationships": result})


@collaborative_edit(
    collaborative_block(create_editor_collaboration_document_id(EEditorCollaborationType.Card, "{card_uid}", "title")),
    collaborative_block(
        create_editor_collaboration_document_id(EEditorCollaborationType.Card, "{card_uid}", "description")
    ),
    collaborative_block(
        create_editor_collaboration_document_id(EEditorCollaborationType.Card, "{card_uid}", "deadline")
    ),
    collaborative_block(
        create_editor_collaboration_document_id(EEditorCollaborationType.Card, "{card_uid}", "members")
    ),
    collaborative_block(create_editor_collaboration_document_id(EEditorCollaborationType.Card, "{card_uid}", "labels")),
    collaborative_block(
        create_editor_collaboration_document_id(EEditorCollaborationType.Card, "{card_uid}", "relationships-parents")
    ),
    collaborative_block(
        create_editor_collaboration_document_id(EEditorCollaborationType.Card, "{card_uid}", "relationships-children")
    ),
)
@AppRouter.schema(permission=ApiPermission.Delete)
@AppRouter.api.put(
    "/board/{project_uid}/card/{card_uid}/archive",
    tags=["Board.Card"],
    description="Archive a card.",
    responses=OpenApiSchema().auth().forbidden().err(404, ApiErrorCode.NF2003).get(),
)
@RoleFilter.add(ProjectRole, [ProjectRoleAction.CardUpdate], RoleFinder.project)
@AuthFilter.add()
def archive_card(
    project_uid: str,
    card_uid: str,
    user_or_bot: User | Bot = Auth.scope("all"),
    service: DomainService = DomainService.scope(),
) -> JsonResponse:
    project = service.project.get_by_id_like(project_uid)
    if project is None:
        raise ApiException.NotFound_404(ApiErrorCode.NF2003)

    result = service.card.archive(user_or_bot, project, card_uid)
    if not result:
        raise ApiException.NotFound_404(ApiErrorCode.NF2003)

    return JsonResponse()


@collaborative_edit(
    collaborative_block(create_editor_collaboration_document_id(EEditorCollaborationType.Card, "{card_uid}", "title")),
    collaborative_block(
        create_editor_collaboration_document_id(EEditorCollaborationType.Card, "{card_uid}", "description")
    ),
    collaborative_block(
        create_editor_collaboration_document_id(EEditorCollaborationType.Card, "{card_uid}", "deadline")
    ),
    collaborative_block(
        create_editor_collaboration_document_id(EEditorCollaborationType.Card, "{card_uid}", "members")
    ),
    collaborative_block(create_editor_collaboration_document_id(EEditorCollaborationType.Card, "{card_uid}", "labels")),
    collaborative_block(
        create_editor_collaboration_document_id(EEditorCollaborationType.Card, "{card_uid}", "relationships-parents")
    ),
    collaborative_block(
        create_editor_collaboration_document_id(EEditorCollaborationType.Card, "{card_uid}", "relationships-children")
    ),
)
@AppRouter.schema(permission=ApiPermission.Delete)
@AppRouter.api.delete(
    "/board/{project_uid}/card/{card_uid}",
    tags=["Board.Card"],
    description="Delete a card. (Only available for archived cards)",
    responses=OpenApiSchema().auth().forbidden().err(404, ApiErrorCode.NF2003).get(),
)
@RoleFilter.add(ProjectRole, [ProjectRoleAction.CardDelete], RoleFinder.project)
@AuthFilter.add()
def delete_card(
    project_uid: str,
    card_uid: str,
    user_or_bot: User | Bot = Auth.scope("all"),
    service: DomainService = DomainService.scope(),
) -> JsonResponse:
    result = service.card.delete(user_or_bot, project_uid, card_uid)
    if not result:
        raise ApiException.NotFound_404(ApiErrorCode.NF2003)

    return JsonResponse()
