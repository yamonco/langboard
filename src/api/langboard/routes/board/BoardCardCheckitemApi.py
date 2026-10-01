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
from langboard_shared.core.types import SafeDateTime
from langboard_shared.core.utils.Converter import convert_python_data
from langboard_shared.domain.models import Bot, ProjectRole, User
from langboard_shared.domain.models.ProjectRole import ProjectRoleAction
from langboard_shared.domain.services import DomainService
from langboard_shared.filter import RoleFilter
from langboard_shared.security import Auth, RoleFinder
from .forms import (
    CardCheckRelatedForm,
    CardifyCheckitemForm,
    ChangeCardCheckitemDeadlineForm,
    ChangeCardCheckitemStatusForm,
    ChangeChildOrderForm,
)


@collaborative_edit(
    collaborative_text(
        create_editor_collaboration_document_id(
            EEditorCollaborationType.Card, "{card_uid}", "checkitem-{checkitem_uid}"
        ),
        "title",
        "title",
    )
)
@AppRouter.schema(form=CardCheckRelatedForm, permission=ApiPermission.Edit)
@AppRouter.api.put(
    "/board/{project_uid}/card/{card_uid}/checkitem/{checkitem_uid}/title",
    tags=["Board.Card.Checkitem"],
    description="Change checkitem title.",
    responses=OpenApiSchema().auth().forbidden().err(404, ApiErrorCode.NF2011).get(),
)
@RoleFilter.add(ProjectRole, [ProjectRoleAction.CardUpdate], RoleFinder.project)
@AuthFilter.add()
def change_checkitem_title(
    project_uid: str,
    card_uid: str,
    checkitem_uid: str,
    form: CardCheckRelatedForm,
    user_or_bot: User | Bot = Auth.scope("all"),
    service: DomainService = DomainService.scope(),
) -> JsonResponse:
    result = service.checkitem.change_title(user_or_bot, project_uid, card_uid, checkitem_uid, form.title)
    if not result:
        raise ApiException.NotFound_404(ApiErrorCode.NF2011)

    return JsonResponse()


@collaborative_edit(
    collaborative_text(
        create_editor_collaboration_document_id(
            EEditorCollaborationType.Card, "{card_uid}", "checkitem-{checkitem_uid}-deadline"
        ),
        "deadline_at",
        "value",
    )
)
@AppRouter.schema(form=ChangeCardCheckitemDeadlineForm, permission=ApiPermission.Edit)
@AppRouter.api.put(
    "/board/{project_uid}/card/{card_uid}/checkitem/{checkitem_uid}/deadline",
    tags=["Board.Card.Checkitem"],
    description="Change checkitem deadline.",
    responses=OpenApiSchema().auth().forbidden().err(404, ApiErrorCode.NF2011).get(),
)
@RoleFilter.add(ProjectRole, [ProjectRoleAction.CardUpdate], RoleFinder.project)
@AuthFilter.add()
def change_checkitem_deadline(
    project_uid: str,
    card_uid: str,
    checkitem_uid: str,
    form: ChangeCardCheckitemDeadlineForm,
    service: DomainService = DomainService.scope(),
) -> JsonResponse:
    deadline_at = None
    if form.deadline_at:
        deadline_at = SafeDateTime.fromisoformat(form.deadline_at)
        if deadline_at.tzinfo is None:
            deadline_at = deadline_at.replace(tzinfo=SafeDateTime.now().astimezone().tzinfo)

    result = service.checkitem.change_deadline(project_uid, card_uid, checkitem_uid, deadline_at)
    if not result:
        raise ApiException.NotFound_404(ApiErrorCode.NF2011)

    return JsonResponse(content={"deadline_at": convert_python_data(deadline_at)})


@AppRouter.schema(form=ChangeChildOrderForm, permission=ApiPermission.Edit)
@AppRouter.api.put(
    "/board/{project_uid}/card/{card_uid}/checkitem/{checkitem_uid}/order",
    tags=["Board.Card.Checkitem"],
    description="Change checkitem order or move to another checklist.",
    responses=OpenApiSchema().auth().forbidden().err(404, ApiErrorCode.NF2011).get(),
)
@RoleFilter.add(ProjectRole, [ProjectRoleAction.CardUpdate], RoleFinder.project)
@AuthFilter.add()
def change_checkitem_order_or_move_checklist(
    project_uid: str,
    card_uid: str,
    checkitem_uid: str,
    form: ChangeChildOrderForm,
    service: DomainService = DomainService.scope(),
) -> JsonResponse:
    result = service.checkitem.change_order(project_uid, card_uid, checkitem_uid, form.order, form.parent_uid)
    if not result:
        raise ApiException.NotFound_404(ApiErrorCode.NF2011)

    return JsonResponse()


@AppRouter.api.put(
    "/board/{project_uid}/card/{card_uid}/checkitem/{checkitem_uid}/status",
    tags=["Board.Card.Checkitem"],
    description="Change checkitem status.",
    responses=(
        OpenApiSchema()
        .auth()
        .forbidden()
        .err(403, ApiErrorCode.PE2003)
        .err(409, ApiErrorCode.EX2002)
        .err(404, ApiErrorCode.NF2011)
        .get()
    ),
)
@RoleFilter.add(ProjectRole, [ProjectRoleAction.CardUpdate], RoleFinder.project)
@AuthFilter.add("user")
def change_checkitem_status(
    project_uid: str,
    card_uid: str,
    checkitem_uid: str,
    form: ChangeCardCheckitemStatusForm,
    user: User = Auth.scope("user"),
    service: DomainService = DomainService.scope(),
) -> JsonResponse:
    checkitem = service.checkitem.get_by_id_like(checkitem_uid)
    if not checkitem:
        raise ApiException.NotFound_404(ApiErrorCode.NF2011)

    if checkitem.user_id and checkitem.user_id != user.id:
        raise ApiException.Forbidden_403(ApiErrorCode.PE2003)

    if form.status.value == "started":
        other_active = [
            work
            for work in service.checkitem.get_active_work(user)
            if work["checkitem"]["uid"] != checkitem.get_uid()
        ]
        if other_active and not form.replace_active:
            raise ApiException.Conflict_409(ApiErrorCode.EX2002)

    result = service.checkitem.change_status(user, project_uid, card_uid, checkitem, form.status, from_api=True)
    if not result:
        raise ApiException.NotFound_404(ApiErrorCode.NF2011)

    return JsonResponse()


@AppRouter.schema(form=CardifyCheckitemForm, permission=ApiPermission.Create)
@AppRouter.api.post(
    "/board/{project_uid}/card/{card_uid}/checkitem/{checkitem_uid}/cardify",
    tags=["Board.Card.Checkitem"],
    description="Cardify checkitem.",
    responses=OpenApiSchema().auth().forbidden().err(403, ApiErrorCode.PE2003).err(404, ApiErrorCode.NF2011).get(),
)
@RoleFilter.add(ProjectRole, [ProjectRoleAction.CardUpdate], RoleFinder.project)
@AuthFilter.add()
def cardify_checkitem(
    project_uid: str,
    card_uid: str,
    checkitem_uid: str,
    form: CardifyCheckitemForm,
    user_or_bot: User | Bot = Auth.scope("all"),
    service: DomainService = DomainService.scope(),
) -> JsonResponse:
    checkitem = service.checkitem.get_by_id_like(checkitem_uid)
    if not checkitem:
        raise ApiException.NotFound_404(ApiErrorCode.NF2011)

    if checkitem.user_id and checkitem.user_id != user_or_bot.id:
        raise ApiException.Forbidden_403(ApiErrorCode.PE2003)

    cardified_card = service.checkitem.cardify(user_or_bot, project_uid, card_uid, checkitem, form.project_column_uid)
    if not cardified_card:
        raise ApiException.NotFound_404(ApiErrorCode.NF2011)

    return JsonResponse()


@AppRouter.schema(permission=ApiPermission.Edit)
@AppRouter.api.put(
    "/board/{project_uid}/card/{card_uid}/checkitem/{checkitem_uid}/toggle-checked",
    tags=["Board.Card.Checkitem"],
    description="Toggle checkitem checked.",
    responses=OpenApiSchema().auth().forbidden().err(403, ApiErrorCode.PE2003).err(404, ApiErrorCode.NF2011).get(),
)
@RoleFilter.add(ProjectRole, [ProjectRoleAction.CardUpdate], RoleFinder.project)
@AuthFilter.add()
def toggle_checkitem_checked(
    project_uid: str,
    card_uid: str,
    checkitem_uid: str,
    user_or_bot: User | Bot = Auth.scope("all"),
    service: DomainService = DomainService.scope(),
) -> JsonResponse:
    checkitem = service.checkitem.get_by_id_like(checkitem_uid)
    if not checkitem:
        raise ApiException.NotFound_404(ApiErrorCode.NF2011)

    if checkitem.user_id and checkitem.user_id != user_or_bot.id:
        raise ApiException.Forbidden_403(ApiErrorCode.PE2003)

    result = service.checkitem.toggle_checked(user_or_bot, project_uid, card_uid, checkitem)
    if not result:
        raise ApiException.NotFound_404(ApiErrorCode.NF2011)

    return JsonResponse()


@collaborative_edit(
    collaborative_block(
        create_editor_collaboration_document_id(
            EEditorCollaborationType.Card, "{card_uid}", "checkitem-{checkitem_uid}"
        )
    ),
    collaborative_block(
        create_editor_collaboration_document_id(
            EEditorCollaborationType.Card, "{card_uid}", "checkitem-{checkitem_uid}-deadline"
        )
    ),
)
@AppRouter.schema(permission=ApiPermission.Delete)
@AppRouter.api.delete(
    "/board/{project_uid}/card/{card_uid}/checkitem/{checkitem_uid}",
    tags=["Board.Card.Checkitem"],
    description="Delete checkitem.",
    responses=OpenApiSchema().auth().forbidden().err(403, ApiErrorCode.PE2003).err(404, ApiErrorCode.NF2011).get(),
)
@RoleFilter.add(ProjectRole, [ProjectRoleAction.CardUpdate], RoleFinder.project)
@AuthFilter.add()
def delete_checkitem(
    project_uid: str,
    card_uid: str,
    checkitem_uid: str,
    user_or_bot: User | Bot = Auth.scope("all"),
    service: DomainService = DomainService.scope(),
) -> JsonResponse:
    checkitem = service.checkitem.get_by_id_like(checkitem_uid)
    if not checkitem:
        raise ApiException.NotFound_404(ApiErrorCode.NF2011)

    if checkitem.user_id and checkitem.user_id != user_or_bot.id:
        raise ApiException.Forbidden_403(ApiErrorCode.PE2003)

    result = service.checkitem.delete(user_or_bot, project_uid, card_uid, checkitem)
    if not result:
        raise ApiException.NotFound_404(ApiErrorCode.NF2011)
    return JsonResponse()
