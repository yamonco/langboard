from typing import Any
import requests
from fastapi import Request, status
from langboard_shared.core.filter import AuthFilter
from langboard_shared.core.routing import (
    ApiException,
    ApiPermission,
    AppRouter,
    BaseFormModel,
    JsonResponse,
    form_model,
)
from langboard_shared.core.schema import OpenApiSchema
from langboard_shared.core.security import AuthSecurity
from langboard_shared.domain.models import User
from langboard_shared.domain.services import DomainService
from langboard_shared.Env import Env
from langboard_shared.security import Auth
from pydantic import Field
from ..auth.SocketAuthorization import authorized_editor_document_subscription
from .EditorSyncPayload import rich_patch_request_fits_limit


def _get_socket_url() -> str:
    return Env.SOCKET_EDITOR_INTERNAL_URL


@form_model
class EditorSyncTextForm(BaseFormModel):
    document_name: str = Field(
        ...,
        title="Editor sync document name",
        description="Collaborative document name. Example: card:<card_uid>:title.",
    )
    field: str = Field(
        ...,
        title="Y.Text field name",
        description="Collaborative text field name inside the document. Example: title.",
    )


@form_model
class PatchEditorSyncTextForm(EditorSyncTextForm):
    value: str = Field(
        ...,
        title="Draft text value",
        description="The full replacement text to write into the active collaborative draft.",
    )


@form_model
class PatchEditorSyncRichForm(BaseFormModel):
    document_name: str = Field(
        ...,
        title="Editor sync rich document name",
        description="Collaborative rich editor document name. Example: card:<card_uid>:description.",
    )
    value: str = Field(
        ...,
        title="Markdown draft value",
        description="The markdown text to apply through the active rich editor client.",
    )


def _create_socket_headers(request: Request) -> dict[str, str]:
    headers: dict[str, str] = {}
    api_token = request.headers.get(
        AuthSecurity.API_TOKEN_HEADER, request.headers.get(AuthSecurity.API_TOKEN_HEADER.lower())
    )
    if api_token:
        headers[AuthSecurity.API_TOKEN_HEADER] = api_token
        return headers

    authorization = request.headers.get(
        AuthSecurity.AUTHORIZATION_HEADER, request.headers.get(AuthSecurity.AUTHORIZATION_HEADER.lower())
    )
    if authorization:
        headers[AuthSecurity.AUTHORIZATION_HEADER] = authorization

    cookie = request.headers.get("cookie")
    if cookie:
        headers["cookie"] = cookie

    return headers


def _forward_to_socket(request: Request, path: str, data: dict[str, Any]) -> JsonResponse:
    try:
        response = requests.post(
            f"{_get_socket_url()}{path}", json=data, headers=_create_socket_headers(request), timeout=10
        )
    except requests.RequestException as error:
        return JsonResponse(content={"message": str(error)}, status_code=status.HTTP_503_SERVICE_UNAVAILABLE)

    try:
        content = response.json()
    except ValueError:
        content = {"message": response.text}

    return JsonResponse(content=content, status_code=response.status_code)


@AppRouter.schema(form=EditorSyncTextForm, permission=ApiPermission.Read)
@AppRouter.api.post(
    "/editor-sync/text",
    tags=["EditorSync"],
    description=(
        "Get the current value of an active collaborative text draft. Use this before patching a draft "
        "when the user asks to revise text that is currently open in an editor."
    ),
    responses=OpenApiSchema().suc({"value": "string"}).auth().forbidden().get(),
)
@AuthFilter.add()
def get_editor_sync_text(request: Request, form: EditorSyncTextForm, user: User = Auth.scope("user")) -> JsonResponse:
    return _forward_to_socket(request, "/editor-sync/text", form.model_dump())


@AppRouter.schema(form=PatchEditorSyncTextForm, permission=ApiPermission.Edit)
@AppRouter.api.post(
    "/editor-sync/text/patch",
    tags=["EditorSync"],
    description=(
        "Replace an active collaborative text draft and broadcast it to connected editors. "
        "Use this instead of normal save/update APIs when the user asks to modify text currently being edited."
    ),
    responses=OpenApiSchema().suc({}).auth().forbidden().get(),
)
@AuthFilter.add()
def patch_editor_sync_text(
    request: Request, form: PatchEditorSyncTextForm, user: User = Auth.scope("user")
) -> JsonResponse:
    return _forward_to_socket(request, "/editor-sync/text/patch", form.model_dump())


@AppRouter.schema(form=PatchEditorSyncRichForm, permission=ApiPermission.Edit)
@AppRouter.api.post(
    "/editor-sync/rich/patch-request",
    tags=["EditorSync"],
    description=(
        "Request the active rich editor client to replace its collaborative draft. "
        "Use this instead of normal save/update APIs when the target is card:<card_uid>:description "
        "or wiki:<wiki_uid>:content and currently open."
    ),
    responses=OpenApiSchema().suc({}).auth().forbidden().get(),
)
@AuthFilter.add()
def request_editor_sync_rich_patch(
    request: Request,
    form: PatchEditorSyncRichForm,
    user: User = Auth.scope("user"),
    service: DomainService = DomainService.scope(),
) -> JsonResponse:
    if not rich_patch_request_fits_limit(form.document_name, form.value):
        return JsonResponse(
            {"message": "Editor sync request exceeded the size limit."},
            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
        )

    subscription = authorized_editor_document_subscription(service, user, form.document_name)
    if not subscription:
        raise ApiException.Forbidden_403()

    return _forward_to_socket(request, "/editor-sync/rich/patch-request", form.model_dump())
