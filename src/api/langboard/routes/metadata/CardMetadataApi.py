from fastapi import Depends
from langboard_shared.core.filter import AuthFilter
from langboard_shared.core.routing import (
    ApiErrorCode,
    ApiException,
    ApiPermission,
    AppRouter,
    EEditorCollaborationType,
    JsonResponse,
    SocketTopic,
    collaborative_block,
    collaborative_edit,
    collaborative_text,
    create_editor_collaboration_document_id,
)
from langboard_shared.core.schema import OpenApiSchema
from langboard_shared.domain.models import Card, CardMetadata, Project, ProjectRole
from langboard_shared.domain.models.ProjectRole import ProjectRoleAction
from langboard_shared.domain.services import DomainService
from langboard_shared.filter import RoleFilter
from langboard_shared.helpers import InfraHelper
from langboard_shared.publishers import MetadataPublisher
from langboard_shared.security import RoleFinder
from .MetadataForm import MetadataDeleteForm, MetadataForm, MetadataGetModel
from .MetadataHelper import create_metadata_api_schema


@AppRouter.schema(permission=ApiPermission.Read)
@AppRouter.api.get(
    "/metadata/project/{project_uid}/card/{card_uid}",
    tags=["Metadata"],
    description="Get card metadata.",
    responses=create_metadata_api_schema("list").err(404, ApiErrorCode.NF2003).get(),
)
@RoleFilter.add(ProjectRole, [ProjectRoleAction.Read], RoleFinder.project)
@AuthFilter.add()
def get_card_metadata(project_uid: str, card_uid: str, service: DomainService = DomainService.scope()) -> JsonResponse:
    params = InfraHelper.get_records_with_foreign_by_params((Project, project_uid), (Card, card_uid))
    if not params:
        raise ApiException.NotFound_404(ApiErrorCode.NF2003)
    _, card = params

    metadata = service.metadata.get_all_as_api(CardMetadata, card, as_dict=True)
    return JsonResponse(content={"metadata": metadata})


@AppRouter.schema(permission=ApiPermission.Read)
@AppRouter.api.get(
    "/metadata/project/{project_uid}/cards",
    tags=["Metadata"],
    description="Get project card metadata.",
    responses=(
        OpenApiSchema()
        .suc({"metadata": {"card_uid": {"key": "value"}}})
        .auth()
        .forbidden()
        .err(404, ApiErrorCode.NF2003)
        .get()
    ),
)
@RoleFilter.add(ProjectRole, [ProjectRoleAction.Read], RoleFinder.project)
@AuthFilter.add()
def get_project_cards_metadata(project_uid: str, service: DomainService = DomainService.scope()) -> JsonResponse:
    project = service.project.get_by_id_like(project_uid)
    if project is None:
        raise ApiException.NotFound_404(ApiErrorCode.NF2003)

    cards = service.card.get_by_project(project)
    metadata = service.metadata.get_all_by_foreign_models_as_api(
        CardMetadata,
        "card_id",
        cards,
    )
    return JsonResponse(content={"metadata": metadata})


@AppRouter.schema(query=MetadataGetModel, permission=ApiPermission.Read)
@AppRouter.api.get(
    "/metadata/project/{project_uid}/card/{card_uid}/key",
    tags=["Metadata"],
    description="Get card metadata by key.",
    responses=create_metadata_api_schema("key").err(404, ApiErrorCode.NF2003).get(),
)
@RoleFilter.add(ProjectRole, [ProjectRoleAction.Read], RoleFinder.project)
@AuthFilter.add()
def get_card_metadata_by_key(
    project_uid: str,
    card_uid: str,
    get_query: MetadataGetModel = Depends(),
    service: DomainService = DomainService.scope(),
) -> JsonResponse:
    params = InfraHelper.get_records_with_foreign_by_params((Project, project_uid), (Card, card_uid))
    if not params:
        raise ApiException.NotFound_404(ApiErrorCode.NF2003)
    _, card = params

    metadata = service.metadata.get_by_key_as_api(CardMetadata, card, get_query.key)
    value = metadata.get("value", None) if metadata else None
    return JsonResponse(content={get_query.key: value})


@collaborative_edit(
    collaborative_text(
        create_editor_collaboration_document_id(EEditorCollaborationType.Card, "{card_uid}", "metadata-{old_key}"),
        "key",
        "key",
    ),
    collaborative_text(
        create_editor_collaboration_document_id(EEditorCollaborationType.Card, "{card_uid}", "metadata-{old_key}"),
        "value",
        "value",
    ),
)
@AppRouter.schema(form=MetadataForm, permission=ApiPermission.Edit)
@AppRouter.api.post(
    "/metadata/project/{project_uid}/card/{card_uid}",
    tags=["Metadata"],
    description="Save card metadata.",
    responses=create_metadata_api_schema().err(404, ApiErrorCode.NF2016).get(),
)
@RoleFilter.add(ProjectRole, [ProjectRoleAction.CardUpdate], RoleFinder.project)
@AuthFilter.add()
def save_card_metadata(
    project_uid: str, card_uid: str, form: MetadataForm, service: DomainService = DomainService.scope()
) -> JsonResponse:
    params = InfraHelper.get_records_with_foreign_by_params((Project, project_uid), (Card, card_uid))
    if not params:
        raise ApiException.NotFound_404(ApiErrorCode.NF2016)
    _, card = params

    metadata = service.metadata.save(CardMetadata, card, form.key, form.value, form.old_key)
    if metadata is None:
        raise ApiException.NotFound_404(ApiErrorCode.NF2016)

    MetadataPublisher.updated_metadata(SocketTopic.BoardCard, card.get_uid(), form.key, form.value, form.old_key)
    return JsonResponse()


@collaborative_edit(
    collaborative_block(
        create_editor_collaboration_document_id(EEditorCollaborationType.Card, "{card_uid}", "metadata-{keys}")
    )
)
@AppRouter.schema(form=MetadataDeleteForm, permission=ApiPermission.Delete)
@AppRouter.api.delete(
    "/metadata/project/{project_uid}/card/{card_uid}",
    tags=["Metadata"],
    description="Delete card metadata.",
    responses=create_metadata_api_schema().err(404, ApiErrorCode.NF2003).get(),
)
@RoleFilter.add(ProjectRole, [ProjectRoleAction.CardUpdate], RoleFinder.project)
@AuthFilter.add()
def delete_card_metadata(
    form: MetadataDeleteForm, project_uid: str, card_uid: str, service: DomainService = DomainService.scope()
) -> JsonResponse:
    params = InfraHelper.get_records_with_foreign_by_params((Project, project_uid), (Card, card_uid))
    if not params:
        raise ApiException.NotFound_404(ApiErrorCode.NF2003)
    _, card = params

    service.metadata.delete(CardMetadata, card, form.keys)

    MetadataPublisher.deleted_metadata(SocketTopic.BoardCard, card.get_uid(), form.keys)
    return JsonResponse()
