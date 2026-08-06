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
    create_editor_collaboration_document_id,
)
from langboard_shared.core.schema import OpenApiSchema
from langboard_shared.domain.models import Bot, CardComment, ProjectRole, User
from langboard_shared.domain.models.ProjectRole import ProjectRoleAction
from langboard_shared.domain.services import DomainService
from langboard_shared.filter import RoleFilter
from langboard_shared.security import Auth, RoleFinder
from .forms import ToggleCardCommentReactionForm


@AppRouter.schema(form=EditorContentModel, permission=ApiPermission.Create)
@AppRouter.api.post(
    "/board/{project_uid}/card/{card_uid}/comment",
    tags=["Board.Card.Comment"],
    description="Add a comment to a card.",
    responses=OpenApiSchema(201).auth().forbidden().err(404, ApiErrorCode.NF2003).get(),
)
@RoleFilter.add(ProjectRole, [ProjectRoleAction.Read], RoleFinder.project)
@AuthFilter.add()
def add_card_comment(
    project_uid: str,
    card_uid: str,
    comment: EditorContentModel,
    user_or_bot: User | Bot = Auth.scope("all"),
    service: DomainService = DomainService.scope(),
) -> JsonResponse:
    result = service.card_comment.create(user_or_bot, project_uid, card_uid, comment)
    if not result:
        raise ApiException.NotFound_404(ApiErrorCode.NF2003)

    return JsonResponse(status_code=status.HTTP_201_CREATED)


@AppRouter.api.get(
    "/board/{project_uid}/card/{card_uid}/comment/{comment_uid}",
    tags=["Board.Card.Comment"],
    description="Get a card comment.",
    responses=(
        OpenApiSchema(200)
        .suc(
            {
                "comment": (
                    CardComment,
                    {
                        "schema": {
                            "user?": User,
                            "bot?": Bot,
                            "reactions": {"<reaction type>": ["<user or bot uid>"]},
                        }
                    },
                ),
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
def get_card_comment(card_uid: str, comment_uid: str, service: DomainService = DomainService.scope()) -> JsonResponse:
    result = service.card_comment.get_as_api(card_uid, comment_uid)
    if not result:
        raise ApiException.NotFound_404(ApiErrorCode.NF2003)

    return JsonResponse(content={"comment": result})


@collaborative_edit(
    collaborative_rich(
        create_editor_collaboration_document_id(EEditorCollaborationType.Card, "{card_uid}", "comment-{comment_uid}"),
        "content",
    )
)
@AppRouter.schema(form=EditorContentModel, permission=ApiPermission.Edit)
@AppRouter.api.put(
    "/board/{project_uid}/card/{card_uid}/comment/{comment_uid}",
    tags=["Board.Card.Comment"],
    description="Update a comment.",
    responses=OpenApiSchema().auth().forbidden().err(403, ApiErrorCode.PE2004).err(404, ApiErrorCode.NF2012).get(),
)
@RoleFilter.add(ProjectRole, [ProjectRoleAction.Read], RoleFinder.project)
@AuthFilter.add()
def update_card_comment(
    project_uid: str,
    card_uid: str,
    comment_uid: str,
    comment: EditorContentModel,
    user_or_bot: User | Bot = Auth.scope("all"),
    service: DomainService = DomainService.scope(),
) -> JsonResponse:
    card_comment = service.card_comment.get_by_id_like(comment_uid)
    if not card_comment:
        raise ApiException.NotFound_404(ApiErrorCode.NF2012)
    if not service.card_comment.can_mutate(user_or_bot, card_comment):
        raise ApiException.Forbidden_403(ApiErrorCode.PE2004)
    result = service.card_comment.update(user_or_bot, project_uid, card_uid, card_comment, comment)
    if not result:
        raise ApiException.NotFound_404(ApiErrorCode.NF2012)

    return JsonResponse()


@collaborative_edit(
    collaborative_block(
        create_editor_collaboration_document_id(EEditorCollaborationType.Card, "{card_uid}", "comment-{comment_uid}")
    )
)
@AppRouter.schema(permission=ApiPermission.Delete)
@AppRouter.api.delete(
    "/board/{project_uid}/card/{card_uid}/comment/{comment_uid}",
    tags=["Board.Card.Comment"],
    description="Delete a comment.",
    responses=OpenApiSchema().auth().forbidden().err(403, ApiErrorCode.PE2004).err(404, ApiErrorCode.NF2012).get(),
)
@RoleFilter.add(ProjectRole, [ProjectRoleAction.Read], RoleFinder.project)
@AuthFilter.add()
def delete_card_comment(
    project_uid: str,
    card_uid: str,
    comment_uid: str,
    user_or_bot: User | Bot = Auth.scope("all"),
    service: DomainService = DomainService.scope(),
) -> JsonResponse:
    card_comment = service.card_comment.get_by_id_like(comment_uid)
    if not card_comment:
        raise ApiException.NotFound_404(ApiErrorCode.NF2012)
    if not service.card_comment.can_mutate(user_or_bot, card_comment):
        raise ApiException.Forbidden_403(ApiErrorCode.PE2004)
    result = service.card_comment.delete(user_or_bot, project_uid, card_uid, card_comment)
    if not result:
        raise ApiException.NotFound_404(ApiErrorCode.NF2012)

    return JsonResponse()


@AppRouter.schema(form=ToggleCardCommentReactionForm, permission=ApiPermission.Edit)
@AppRouter.api.post(
    "/board/{project_uid}/card/{card_uid}/comment/{comment_uid}/react",
    tags=["Board.Card.Comment"],
    description="Toggle reaction on a comment.",
    responses=OpenApiSchema().suc({"is_reacted": "bool"}).auth().forbidden().err(404, ApiErrorCode.NF2012).get(),
)
@RoleFilter.add(ProjectRole, [ProjectRoleAction.Read], RoleFinder.project)
@AuthFilter.add()
def toggle_reaction_card_comment(
    project_uid: str,
    card_uid: str,
    comment_uid: str,
    form: ToggleCardCommentReactionForm,
    user_or_bot: User | Bot = Auth.scope("all"),
    service: DomainService = DomainService.scope(),
) -> JsonResponse:
    card_comment = service.card_comment.get_by_id_like(comment_uid)
    if not card_comment:
        raise ApiException.NotFound_404(ApiErrorCode.NF2012)
    result = service.card_comment.toggle_reaction(user_or_bot, project_uid, card_uid, card_comment, form.reaction)
    if result is None:
        raise ApiException.NotFound_404(ApiErrorCode.NF2012)

    return JsonResponse(content={"is_reacted": result})
