from fastapi import Request, status
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
    collaborative_text,
    create_editor_collaboration_document_id,
)
from langboard_shared.core.schema import OpenApiSchema
from langboard_shared.domain.models import Bot, Checkitem, Checklist, ProjectRole, User
from langboard_shared.domain.models.ProjectRole import ProjectRoleAction
from langboard_shared.domain.services import DomainService
from langboard_shared.filter import RoleFilter
from langboard_shared.security import Auth, RoleFinder
from .CardAccess import require_card_child, require_visible_card
from .forms import CardChecklistNotifyForm, CardCheckRelatedForm, ChangeRootOrderForm


@AppRouter.schema(permission=ApiPermission.Read)
@AppRouter.api.get(
    "/board/{project_uid}/card/{card_uid}/checklist",
    tags=["Board.Card"],
    description="Get card checklists.",
    responses=(
        OpenApiSchema()
        .suc(
            {
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
            }
        )
        .auth()
        .forbidden()
        .get()
    ),
)
@RoleFilter.add(ProjectRole, [ProjectRoleAction.Read], RoleFinder.project)
@AuthFilter.add()
def get_card_checklists(
    project_uid: str,
    card_uid: str,
    request: Request,
    user_or_bot: User | Bot = Auth.scope("all"),
    service: DomainService = DomainService.scope(),
) -> JsonResponse:
    require_visible_card(project_uid, card_uid, request, user_or_bot, service)
    checklists = service.checklist.get_api_list_by_card(card_uid)
    return JsonResponse(content={"checklists": checklists})


@AppRouter.schema(form=CardCheckRelatedForm, permission=ApiPermission.Create)
@AppRouter.api.post(
    "/board/{project_uid}/card/{card_uid}/checklist",
    tags=["Board.Card.Checklist"],
    description="Create a checklist.",
    responses=(
        OpenApiSchema().suc({"checklist": Checklist}, 201).auth().forbidden().err(404, ApiErrorCode.NF2003).get()
    ),
)
@RoleFilter.add(ProjectRole, [ProjectRoleAction.CardUpdate], RoleFinder.project)
@AuthFilter.add()
def create_checklist(
    project_uid: str,
    card_uid: str,
    request: Request,
    form: CardCheckRelatedForm,
    user_or_bot: User | Bot = Auth.scope("all"),
    service: DomainService = DomainService.scope(),
) -> JsonResponse:
    require_visible_card(project_uid, card_uid, request, user_or_bot, service)
    result = service.checklist.create(user_or_bot, project_uid, card_uid, form.title)
    if not result:
        raise ApiException.NotFound_404(ApiErrorCode.NF2003)

    return JsonResponse(
        content={
            "checklist": {
                **result.api_response(),
                "checkitems": [],
            }
        },
        status_code=status.HTTP_201_CREATED,
    )


@AppRouter.schema(form=CardCheckRelatedForm, permission=ApiPermission.Create)
@AppRouter.api.post(
    "/board/{project_uid}/card/{card_uid}/checklist/{checklist_uid}/checkitem",
    tags=["Board.Card.Checklist"],
    description="Create a checkitem.",
    responses=OpenApiSchema().suc({"checkitem": Checkitem}, 201).auth().forbidden().err(404, ApiErrorCode.NF2010).get(),
)
@RoleFilter.add(ProjectRole, [ProjectRoleAction.CardUpdate], RoleFinder.project)
@AuthFilter.add()
def create_checkitem(
    project_uid: str,
    card_uid: str,
    request: Request,
    checklist_uid: str,
    form: CardCheckRelatedForm,
    user_or_bot: User | Bot = Auth.scope("all"),
    service: DomainService = DomainService.scope(),
) -> JsonResponse:
    card = require_visible_card(project_uid, card_uid, request, user_or_bot, service)
    require_card_child(card, Checklist, checklist_uid)
    result = service.checkitem.create(user_or_bot, project_uid, card_uid, checklist_uid, form.title)
    if not result:
        raise ApiException.NotFound_404(ApiErrorCode.NF2010)

    return JsonResponse(
        content={"checkitem": {**result.api_response(), "card_uid": card_uid}}, status_code=status.HTTP_201_CREATED
    )


@AppRouter.schema(form=CardChecklistNotifyForm, permission=ApiPermission.Create)
@AppRouter.api.post(
    "/board/{project_uid}/card/{card_uid}/checklist/{checklist_uid}/notify",
    tags=["Board.Card.Checklist"],
    description="Notify members of the checklist.",
    responses=OpenApiSchema().auth().forbidden().err(404, ApiErrorCode.NF2010).get(),
)
@RoleFilter.add(ProjectRole, [ProjectRoleAction.CardUpdate], RoleFinder.project)
@AuthFilter.add()
def notify_checklist(
    project_uid: str,
    card_uid: str,
    request: Request,
    checklist_uid: str,
    form: CardChecklistNotifyForm,
    user_or_bot: User | Bot = Auth.scope("all"),
    service: DomainService = DomainService.scope(),
) -> JsonResponse:
    card = require_visible_card(project_uid, card_uid, request, user_or_bot, service)
    require_card_child(card, Checklist, checklist_uid)
    result = service.checklist.notify(user_or_bot, project_uid, card_uid, checklist_uid, form.user_uids)
    if not result:
        raise ApiException.NotFound_404(ApiErrorCode.NF2010)

    return JsonResponse()


@collaborative_edit(
    collaborative_text(
        create_editor_collaboration_document_id(
            EEditorCollaborationType.Card, "{card_uid}", "checklist-{checklist_uid}"
        ),
        "title",
        "title",
    )
)
@AppRouter.schema(form=CardCheckRelatedForm, permission=ApiPermission.Edit)
@AppRouter.api.put(
    "/board/{project_uid}/card/{card_uid}/checklist/{checklist_uid}/title",
    tags=["Board.Card.Checklist"],
    description="Change checklist title.",
    responses=OpenApiSchema().auth().forbidden().err(404, ApiErrorCode.NF2010).get(),
)
@RoleFilter.add(ProjectRole, [ProjectRoleAction.CardUpdate], RoleFinder.project)
@AuthFilter.add()
def change_checklist_title(
    project_uid: str,
    card_uid: str,
    request: Request,
    checklist_uid: str,
    form: CardCheckRelatedForm,
    user_or_bot: User | Bot = Auth.scope("all"),
    service: DomainService = DomainService.scope(),
) -> JsonResponse:
    card = require_visible_card(project_uid, card_uid, request, user_or_bot, service)
    require_card_child(card, Checklist, checklist_uid)
    result = service.checklist.change_title(user_or_bot, project_uid, card_uid, checklist_uid, form.title)
    if not result:
        raise ApiException.NotFound_404(ApiErrorCode.NF2010)

    return JsonResponse()


@AppRouter.schema(form=ChangeRootOrderForm, permission=ApiPermission.Edit)
@AppRouter.api.put(
    "/board/{project_uid}/card/{card_uid}/checklist/{checklist_uid}/order",
    tags=["Board.Card.Checklist"],
    description="Change checklist order.",
    responses=OpenApiSchema().auth().forbidden().err(404, ApiErrorCode.NF2010).get(),
)
@RoleFilter.add(ProjectRole, [ProjectRoleAction.CardUpdate], RoleFinder.project)
@AuthFilter.add()
def change_checklist_order(
    project_uid: str,
    card_uid: str,
    request: Request,
    checklist_uid: str,
    form: ChangeRootOrderForm,
    user_or_bot: User | Bot = Auth.scope("all"),
    service: DomainService = DomainService.scope(),
) -> JsonResponse:
    card = require_visible_card(project_uid, card_uid, request, user_or_bot, service)
    require_card_child(card, Checklist, checklist_uid)
    result = service.checklist.change_order(project_uid, card_uid, checklist_uid, form.order)
    if not result:
        raise ApiException.NotFound_404(ApiErrorCode.NF2010)

    return JsonResponse()


@AppRouter.schema(permission=ApiPermission.Edit)
@AppRouter.api.put(
    "/board/{project_uid}/card/{card_uid}/checklist/{checklist_uid}/toggle-checked",
    tags=["Board.Card.Checklist"],
    description="Toggle checklist checked.",
    responses=OpenApiSchema().auth().forbidden().err(404, ApiErrorCode.NF2010).get(),
)
@RoleFilter.add(ProjectRole, [ProjectRoleAction.CardUpdate], RoleFinder.project)
@AuthFilter.add()
def toggle_checklist_checked(
    project_uid: str,
    card_uid: str,
    request: Request,
    checklist_uid: str,
    user_or_bot: User | Bot = Auth.scope("all"),
    service: DomainService = DomainService.scope(),
) -> JsonResponse:
    card = require_visible_card(project_uid, card_uid, request, user_or_bot, service)
    require_card_child(card, Checklist, checklist_uid)
    result = service.checklist.toggle_checked(user_or_bot, project_uid, card_uid, checklist_uid)
    if not result:
        raise ApiException.NotFound_404(ApiErrorCode.NF2010)

    return JsonResponse()


@collaborative_edit(
    collaborative_block(
        create_editor_collaboration_document_id(
            EEditorCollaborationType.Card, "{card_uid}", "checklist-{checklist_uid}"
        )
    )
)
@AppRouter.schema(permission=ApiPermission.Delete)
@AppRouter.api.delete(
    "/board/{project_uid}/card/{card_uid}/checklist/{checklist_uid}",
    tags=["Board.Card.Checklist"],
    description="Delete a checklist.",
    responses=OpenApiSchema().auth().forbidden().err(404, ApiErrorCode.NF2010).get(),
)
@RoleFilter.add(ProjectRole, [ProjectRoleAction.CardUpdate], RoleFinder.project)
@AuthFilter.add()
def delete_checklist(
    project_uid: str,
    card_uid: str,
    request: Request,
    checklist_uid: str,
    user_or_bot: User | Bot = Auth.scope("all"),
    service: DomainService = DomainService.scope(),
) -> JsonResponse:
    card = require_visible_card(project_uid, card_uid, request, user_or_bot, service)
    require_card_child(card, Checklist, checklist_uid)
    result = service.checklist.delete(user_or_bot, project_uid, card_uid, checklist_uid)
    if not result:
        raise ApiException.NotFound_404(ApiErrorCode.NF2010)

    return JsonResponse()
