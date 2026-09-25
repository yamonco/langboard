from fastapi import File, UploadFile, status
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
from langboard_shared.core.routing.Exception import MissingException
from langboard_shared.core.schema import OpenApiSchema
from langboard_shared.core.storage import Storage, StorageName
from langboard_shared.core.utils.Converter import convert_python_data
from langboard_shared.domain.models import Bot, Card, Project, ProjectRole, ProjectWiki, ProjectWikiAttachment, User
from langboard_shared.domain.models.ProjectRole import ProjectRoleAction
from langboard_shared.domain.services import DomainService
from langboard_shared.filter import RoleFilter
from langboard_shared.helpers import InfraHelper
from langboard_shared.security import Auth, RoleFinder
from .forms import (
    AssigneesForm,
    ChangeChildOrderForm,
    ChangeWikiDetailsForm,
    ChangeWikiPublicForm,
    WikiForm,
)


@AppRouter.schema(permission=ApiPermission.Read)
@AppRouter.api.get(
    "/board/{project_uid}/wikis",
    tags=["Board.Wiki"],
    description="Get project wikis.",
    responses=(
        OpenApiSchema()
        .suc(
            {
                "wikis": [
                    (
                        ProjectWiki,
                        {
                            "schema": {
                                "assigned_members": [User],
                                "linked_card_uid?": "string",
                            }
                        },
                    )
                ],
                "project_members": [User],
            }
        )
        .auth()
        .forbidden()
        .err(404, ApiErrorCode.NF2001)
        .get()
    ),
)
@RoleFilter.add(ProjectRole, [ProjectRoleAction.Read], RoleFinder.project)
@AuthFilter.add()
def get_project_wikis(
    project_uid: str,
    user_or_bot: User | Bot = Auth.scope("all"),
    service: DomainService = DomainService.scope(),
) -> JsonResponse:
    project = service.project.get_by_id_like(project_uid)
    if project is None:
        raise ApiException.NotFound_404(ApiErrorCode.NF2001)
    wikis = service.project_wiki.get_api_list(user_or_bot, project_uid)
    project_members = service.project.get_api_assigned_user_list(project)
    return JsonResponse(content={"wikis": wikis, "project_members": project_members})


@AppRouter.schema(permission=ApiPermission.Read)
@AppRouter.api.get(
    "/board/{project_uid}/wiki/{wiki_uid}",
    tags=["Board.Wiki"],
    description="Get project wiki details.",
    responses=(
        OpenApiSchema()
        .suc(
            {
                "wiki": (
                    ProjectWiki,
                    {
                        "schema": {
                            "assigned_members": [User],
                            "linked_card_uid?": "string",
                        }
                    },
                )
            }
        )
        .auth()
        .forbidden()
        .err(404, ApiErrorCode.NF2008)
        .get()
    ),
)
@RoleFilter.add(ProjectRole, [ProjectRoleAction.Read], RoleFinder.project)
@AuthFilter.add()
def get_project_wiki_details(
    project_uid: str,
    wiki_uid: str,
    user_or_bot: User | Bot = Auth.scope("all"),
    service: DomainService = DomainService.scope(),
) -> JsonResponse:
    params = InfraHelper.get_records_with_foreign_by_params((Project, project_uid), (ProjectWiki, wiki_uid))
    if not params:
        raise ApiException.NotFound_404(ApiErrorCode.NF2008)
    project, project_wiki = params

    api_wiki = service.project_wiki.convert_to_api_response(user_or_bot, project, project_wiki)
    if not api_wiki:
        raise ApiException.NotFound_404(ApiErrorCode.NF2008)

    api_wiki["linked_card_uid"] = service.project_wiki.get_linked_card_uid(project, project_wiki)
    return JsonResponse(content={"wiki": api_wiki})


@AppRouter.schema(form=WikiForm, permission=ApiPermission.Create)
@AppRouter.api.post(
    "/board/{project_uid}/wiki",
    tags=["Board.Wiki"],
    description="Create a project wiki.",
    responses=(
        OpenApiSchema()
        .suc(
            {
                "wiki": (
                    ProjectWiki,
                    {
                        "schema": {
                            "assigned_members": [User],
                        }
                    },
                )
            },
            201,
        )
        .auth()
        .forbidden()
        .err(404, ApiErrorCode.NF2001)
        .get()
    ),
)
@RoleFilter.add(ProjectRole, [ProjectRoleAction.Read], RoleFinder.project)
@AuthFilter.add()
def create_project_wiki(
    project_uid: str,
    form: WikiForm,
    user_or_bot: User | Bot = Auth.scope("all"),
    service: DomainService = DomainService.scope(),
) -> JsonResponse:
    result = service.project_wiki.create(user_or_bot, project_uid, form.title, form.content)
    if not result:
        raise ApiException.NotFound_404(ApiErrorCode.NF2001)
    _, api_wiki = result

    return JsonResponse(content={"wiki": api_wiki}, status_code=status.HTTP_201_CREATED)


@AppRouter.schema(permission=ApiPermission.Create)
@AppRouter.api.post(
    "/board/{project_uid}/wiki/{wiki_uid}/linked-card",
    tags=["Board.Wiki"],
    description="Create or return the board card linked to a project Wiki.",
    responses=(
        OpenApiSchema()
        .suc({"card": (Card, {"schema": {"linked_resource": "object"}}), "created": "boolean"}, 201)
        .suc({"card": (Card, {"schema": {"linked_resource": "object"}}), "created": "boolean"}, 200)
        .auth()
        .forbidden()
        .err(404, ApiErrorCode.NF2008)
        .get()
    ),
)
@RoleFilter.add(ProjectRole, [ProjectRoleAction.CardUpdate], RoleFinder.project)
@AuthFilter.add()
def create_wiki_linked_card(
    project_uid: str,
    wiki_uid: str,
    user_or_bot: User | Bot = Auth.scope("all"),
    service: DomainService = DomainService.scope(),
) -> JsonResponse:
    result = service.card.create_linked_wiki_card(
        user_or_bot,
        project_uid,
        wiki_uid,
    )
    if result is None:
        raise ApiException.NotFound_404(ApiErrorCode.NF2008)
    _, api_card, created = result
    return JsonResponse(
        content={"card": api_card, "created": created},
        status_code=status.HTTP_201_CREATED if created else status.HTTP_200_OK,
    )


@collaborative_edit(
    collaborative_text(
        create_editor_collaboration_document_id(EEditorCollaborationType.Wiki, "{wiki_uid}", "title"), "title", "title"
    ),
    collaborative_rich(
        create_editor_collaboration_document_id(EEditorCollaborationType.Wiki, "{wiki_uid}", "content"),
        "content",
    ),
)
@AppRouter.schema(form=ChangeWikiDetailsForm, permission=ApiPermission.Edit)
@AppRouter.api.put(
    "/board/{project_uid}/wiki/{wiki_uid}/details",
    tags=["Board.Wiki"],
    description="Change project wiki details.",
    responses=(
        OpenApiSchema()
        .suc({"title?": "string", "content?": EditorContentModel})
        .auth()
        .forbidden()
        .err(403, ApiErrorCode.PE2005)
        .err(404, ApiErrorCode.NF2008)
        .get()
    ),
)
@RoleFilter.add(ProjectRole, [ProjectRoleAction.Read], RoleFinder.project)
@AuthFilter.add()
def change_project_wiki_details(
    project_uid: str,
    wiki_uid: str,
    form: ChangeWikiDetailsForm,
    user_or_bot: User | Bot = Auth.scope("all"),
    service: DomainService = DomainService.scope(),
) -> JsonResponse:
    project_wiki = service.project_wiki.get_by_id_like(wiki_uid)
    if not project_wiki:
        raise ApiException.NotFound_404(ApiErrorCode.NF2008)

    if isinstance(user_or_bot, User) and not service.project_wiki.is_assigned(user_or_bot, project_wiki):
        raise ApiException.Forbidden_403(ApiErrorCode.PE2005)

    form_dict = {}
    for key in ChangeWikiDetailsForm.model_fields:
        value = getattr(form, key)
        if value is None:
            continue
        form_dict[key] = value

    result = service.project_wiki.update(user_or_bot, project_uid, wiki_uid, form_dict)
    if not result:
        raise ApiException.NotFound_404(ApiErrorCode.NF2008)

    if result is True:
        response = {}
        for key in ChangeWikiDetailsForm.model_fields:
            value = getattr(form, key, None)
            if value is None:
                continue
            response[key] = convert_python_data(value)
        return JsonResponse(content=response)

    return JsonResponse(content=result)


@AppRouter.schema(form=ChangeWikiPublicForm, permission=ApiPermission.Edit)
@AppRouter.api.put(
    "/board/{project_uid}/wiki/{wiki_uid}/public",
    tags=["Board.Wiki"],
    description="Change project wiki public status.",
    responses=OpenApiSchema().auth().forbidden().err(403, ApiErrorCode.PE2005).err(404, ApiErrorCode.NF2008).get(),
)
@RoleFilter.add(ProjectRole, [ProjectRoleAction.Read], RoleFinder.project)
@AuthFilter.add()
def change_project_wiki_public(
    project_uid: str,
    wiki_uid: str,
    form: ChangeWikiPublicForm,
    user_or_bot: User | Bot = Auth.scope("all"),
    service: DomainService = DomainService.scope(),
) -> JsonResponse:
    project_wiki = service.project_wiki.get_by_id_like(wiki_uid)
    if not project_wiki:
        raise ApiException.NotFound_404(ApiErrorCode.NF2008)

    if isinstance(user_or_bot, User) and not service.project_wiki.is_assigned(user_or_bot, project_wiki):
        raise ApiException.Forbidden_403(ApiErrorCode.PE2005)

    result = service.project_wiki.change_public(user_or_bot, project_uid, project_wiki, form.is_public)
    if not result:
        raise ApiException.NotFound_404(ApiErrorCode.NF2008)

    return JsonResponse()


@collaborative_edit(
    collaborative_text(
        create_editor_collaboration_document_id(EEditorCollaborationType.Wiki, "{wiki_uid}", "private-assignees"),
        "assignees",
        "selected-member-uids",
    )
)
@AppRouter.schema(form=AssigneesForm, permission=ApiPermission.Edit)
@AppRouter.api.put(
    "/board/{project_uid}/wiki/{wiki_uid}/assignees",
    tags=["Board.Wiki"],
    description="Update project wiki assignees.",
    responses=OpenApiSchema().auth().forbidden().err(403, ApiErrorCode.PE2005).err(404, ApiErrorCode.NF2008).get(),
)
@RoleFilter.add(ProjectRole, [ProjectRoleAction.Read], RoleFinder.project)
@AuthFilter.add("user")
def update_project_wiki_assignees(
    project_uid: str,
    wiki_uid: str,
    form: AssigneesForm,
    user: User = Auth.scope("user"),
    service: DomainService = DomainService.scope(),
) -> JsonResponse:
    project_wiki = service.project_wiki.get_by_id_like(wiki_uid)
    if not project_wiki:
        raise ApiException.NotFound_404(ApiErrorCode.NF2008)

    if not service.project_wiki.is_assigned(user, project_wiki):
        raise ApiException.Forbidden_403(ApiErrorCode.PE2005)

    if not form.assignees:
        raise MissingException("body", "assignees")

    result = service.project_wiki.update_assignees(user, project_uid, project_wiki, form.assignees)
    if not result:
        raise ApiException.NotFound_404(ApiErrorCode.NF2008)

    return JsonResponse()


@AppRouter.schema(form=ChangeChildOrderForm, permission=ApiPermission.Edit)
@AppRouter.api.put(
    "/board/{project_uid}/wiki/{wiki_uid}/order",
    tags=["Board.Wiki"],
    description="Change project wiki order.",
    responses=OpenApiSchema().auth().forbidden().err(404, ApiErrorCode.NF2008).get(),
)
@RoleFilter.add(ProjectRole, [ProjectRoleAction.Read], RoleFinder.project)
@AuthFilter.add()
def change_project_wiki_order(
    project_uid: str,
    wiki_uid: str,
    form: ChangeChildOrderForm,
    service: DomainService = DomainService.scope(),
) -> JsonResponse:
    result = service.project_wiki.change_order(project_uid, wiki_uid, form.order)
    if not result:
        raise ApiException.NotFound_404(ApiErrorCode.NF2008)

    return JsonResponse()


@AppRouter.api.post(
    "/board/{project_uid}/wiki/{wiki_uid}/attachment",
    tags=["Board.Wiki"],
    responses=(
        OpenApiSchema()
        .suc((ProjectWikiAttachment, {"schema": {"user": User}}), 201)
        .auth()
        .forbidden()
        .err(404, ApiErrorCode.NF2008)
        .err(500, ApiErrorCode.OP1002)
        .get()
    ),
)
@RoleFilter.add(ProjectRole, [ProjectRoleAction.Read], RoleFinder.project)
@AuthFilter.add("user")
def upload_wiki_attachment(
    project_uid: str,
    wiki_uid: str,
    attachment: UploadFile = File(),
    user: User = Auth.scope("user"),
    service: DomainService = DomainService.scope(),
) -> JsonResponse:
    if not attachment:
        raise MissingException("body", "attachment")

    file_model = Storage.upload(attachment, StorageName.Wiki)
    if not file_model:
        raise ApiException.InternalServerError_500(ApiErrorCode.OP1002)

    result = service.project_wiki.upload_attachment(user, project_uid, wiki_uid, file_model)
    if not result:
        raise ApiException.NotFound_404(ApiErrorCode.NF2008)

    return JsonResponse(
        content={**result.api_response(), "user": user.api_response()},
        status_code=status.HTTP_201_CREATED,
    )


@collaborative_edit(
    collaborative_block(create_editor_collaboration_document_id(EEditorCollaborationType.Wiki, "{wiki_uid}", "title")),
    collaborative_block(
        create_editor_collaboration_document_id(EEditorCollaborationType.Wiki, "{wiki_uid}", "content")
    ),
    collaborative_block(
        create_editor_collaboration_document_id(EEditorCollaborationType.Wiki, "{wiki_uid}", "private-assignees")
    ),
)
@AppRouter.schema(permission=ApiPermission.Delete)
@AppRouter.api.delete(
    "/board/{project_uid}/wiki/{wiki_uid}",
    tags=["Board.Wiki"],
    description="Delete project wiki.",
    responses=OpenApiSchema().auth().forbidden().err(403, ApiErrorCode.PE2005).err(404, ApiErrorCode.NF2008).get(),
)
@RoleFilter.add(ProjectRole, [ProjectRoleAction.Read], RoleFinder.project)
@AuthFilter.add()
def delete_project_wiki(
    project_uid: str,
    wiki_uid: str,
    user_or_bot: User | Bot = Auth.scope("all"),
    service: DomainService = DomainService.scope(),
) -> JsonResponse:
    project_wiki = service.project_wiki.get_by_id_like(wiki_uid)
    if not project_wiki:
        raise ApiException.NotFound_404(ApiErrorCode.NF2008)

    if isinstance(user_or_bot, User) and not service.project_wiki.is_assigned(user_or_bot, project_wiki):
        raise ApiException.Forbidden_403(ApiErrorCode.PE2005)

    result = service.project_wiki.delete(user_or_bot, project_uid, project_wiki)
    if not result:
        raise ApiException.NotFound_404(ApiErrorCode.NF2008)

    return JsonResponse()
