from datetime import timezone
from secrets import compare_digest
from typing import Any
import requests
from fastapi import Query, Request, status
from jwt import ExpiredSignatureError
from langboard.card_workspace.application import get_card_bundle
from langboard.card_workspace.domain import CardBundleInclude, CommentPage, SectionPage
from langboard.card_workspace.infrastructure import NativeCardWorkspaceAdapter
from langboard.routes.settings.Form import CopyOllamaModelForm, OllamaModelForm
from langboard.routes.settings.OllamaApi import copy_ollama_model, delete_ollama_model, pull_ollama_model
from langboard_shared.ai.BoardChatAttachment import (
    delete_board_chat_attachment_ticket,
    get_board_chat_attachment_ticket,
    schedule_board_chat_attachment_reconciliation,
    set_board_chat_attachment_ticket,
)
from langboard_shared.ai.LangflowFileClient import LangflowFileClient
from langboard_shared.core.logger import Logger
from langboard_shared.core.routing import (
    GLOBAL_TOPIC_ID,
    ApiErrorCode,
    ApiException,
    AppRouter,
    EEditorCollaborationType,
    JsonResponse,
    SocketTopic,
)
from langboard_shared.core.routing.ApiPermission import ApiPermission
from langboard_shared.core.security import AuthSecurity
from langboard_shared.core.types import SnowflakeID
from langboard_shared.domain.models import ChatSession, InternalBotRun, Project, ProjectChatSession, User
from langboard_shared.domain.models.BaseBotModel import BotPlatform, BotPlatformRunningType
from langboard_shared.domain.models.bases import ALL_GRANTED
from langboard_shared.domain.models.InternalBot import InternalBot, InternalBotType
from langboard_shared.domain.models.InternalBotRun import InternalBotRunKind, InternalBotRunStatus
from langboard_shared.domain.models.ProjectAssignedInternalBot import ProjectAssignedInternalBot
from langboard_shared.domain.models.ProjectRole import ProjectRoleAction
from langboard_shared.domain.services import DomainService
from langboard_shared.Env import Env
from langboard_shared.publishers import GraphApprovalPublisher
from langboard_shared.security import Auth
from .forms import (
    SocketBoardChatCancelForm,
    SocketBoardChatFinishForm,
    SocketBoardChatLeaseForm,
    SocketBoardChatPauseForm,
    SocketBoardChatResumeClaimForm,
    SocketBoardChatResumeResultForm,
    SocketBoardChatRunForm,
    SocketBoardChatStartForm,
    SocketChatResumeAuthorizationForm,
    SocketEditorAiAuthorizationForm,
    SocketEditorCancelForm,
    SocketEditorDocumentAuthorizationForm,
    SocketEditorDocumentsAuthorizationForm,
    SocketEditorResumeClaimForm,
    SocketEditorRunForm,
    SocketEditorStatusForm,
    SocketSubscriptionAuthorizationForm,
)
from .SocketAuthorization import (
    authorized_editor_document_subscription,
    is_editor_document_write_authorized,
    is_subscription_authorized,
)


SOCKET_INTERNAL_API_CONTRACT_VERSION = 1
_logger = Logger.use("socket-auth")


def _authenticate_socket_user(request: Request) -> User:
    authorization = request.headers.get(AuthSecurity.AUTHORIZATION_HEADER, "")
    scheme, separator, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not separator or not token.strip():
        raise ApiException.Unauthorized_401()

    try:
        payload = AuthSecurity.decode_access_token(token.strip())
        user_id = int(payload["sub"])
    except ExpiredSignatureError as error:
        raise ApiException.Unauthorized_401(ApiErrorCode.AU1004) from error
    except Exception as error:
        raise ApiException.Unauthorized_401() from error

    if user_id <= 0 or payload.get("internal"):
        raise ApiException.Unauthorized_401()

    user = Auth.get_user_by_id(user_id)
    if not isinstance(user, User) or user.deleted_at is not None or user.activated_at is None:
        raise ApiException.Unauthorized_401()

    return user


def _authorize_socket_ollama(request: Request, service: DomainService) -> None:
    user = _authenticate_socket_user(request)
    if not is_subscription_authorized(service, user, SocketTopic.OllamaManager, GLOBAL_TOPIC_ID):
        raise ApiException.Forbidden_403()


@AppRouter.api.post("/auth/socket/ollama/models/copy", tags=["Auth"])
def copy_socket_ollama_model(
    request: Request, form: CopyOllamaModelForm, service: DomainService = DomainService.scope()
) -> JsonResponse:
    _authorize_socket_ollama(request, service)
    return copy_ollama_model(form)


@AppRouter.api.delete("/auth/socket/ollama/models", tags=["Auth"])
def delete_socket_ollama_model(
    request: Request, form: OllamaModelForm, service: DomainService = DomainService.scope()
) -> JsonResponse:
    _authorize_socket_ollama(request, service)
    return delete_ollama_model(form)


@AppRouter.api.post("/auth/socket/ollama/models/pull", tags=["Auth"])
def pull_socket_ollama_model(
    request: Request, form: OllamaModelForm, service: DomainService = DomainService.scope()
) -> JsonResponse:
    _authorize_socket_ollama(request, service)
    return pull_ollama_model(form, service)


def _authenticate_editor_http_user(request: Request) -> User:
    if request.headers.get(AuthSecurity.API_TOKEN_HEADER):
        user = Auth.validate_user_by_api_token(request.headers)
    else:
        user = Auth.validate(request.headers)

    if not isinstance(user, User) or user.deleted_at is not None or user.activated_at is None:
        raise ApiException.Unauthorized_401()

    return user


@AppRouter.api.post("/auth/socket", tags=["Auth"])
def authenticate_socket(request: Request) -> JsonResponse:
    user = _authenticate_socket_user(request)
    return JsonResponse({"user_uid": user.get_uid()})


@AppRouter.api.post("/auth/socket/subscriptions", tags=["Auth"])
def authorize_socket_subscriptions(
    request: Request,
    form: SocketSubscriptionAuthorizationForm,
    service: DomainService = DomainService.scope(),
) -> JsonResponse:
    user = _authenticate_socket_user(request)
    authorized = [
        {"topic": item.topic.value, "topic_id": item.topic_id}
        for item in form.subscriptions
        if is_subscription_authorized(service, user, item.topic, item.topic_id)
    ]
    return JsonResponse({"authorized": authorized})


def _decode_socket_uid(uid: str) -> SnowflakeID:
    try:
        model_id = SnowflakeID.from_short_code(uid)
    except ValueError as error:
        raise ApiException.Forbidden_403() from error
    if not model_id:
        raise ApiException.Forbidden_403()
    return model_id


def _authenticate_internal_socket(request: Request) -> None:
    secret = Env.SOCKET_PHOENIX_INTERNAL_SECRET
    if len(secret) < 32:
        raise ApiException.ServiceUnavailable_503()
    provided = request.headers.get("X-Socket-Internal-Secret", "")
    if not compare_digest(provided.encode(), secret.encode()):
        raise ApiException.Unauthorized_401()


@AppRouter.api.get("/auth/socket/capabilities", tags=["Auth"])
def get_socket_capabilities(request: Request) -> JsonResponse:
    _authenticate_internal_socket(request)
    return JsonResponse({"contract_version": SOCKET_INTERNAL_API_CONTRACT_VERSION})


def _cleanup_board_chat_attachment(service: DomainService, run: InternalBotRun, *, delete_external: bool) -> None:
    request_payload = run.request_payload
    attachment = request_payload.get("attachment") if isinstance(request_payload, dict) else None
    if not isinstance(attachment, dict):
        return
    token = attachment.get("token")
    file_id = attachment.get("file_id")
    if not isinstance(token, str) or not token or not isinstance(file_id, str) or not file_id:
        return
    if delete_external:
        bot = service.internal_bot.get_by_id_like(run.internal_bot_id)
        if bot is None or not LangflowFileClient.delete(bot, file_id):
            try:
                schedule_board_chat_attachment_reconciliation(run.get_uid())
            except Exception:
                _logger.exception("Could not schedule durable attachment reconciliation")
            return
    delete_board_chat_attachment_ticket(token)


def _authorize_board_chat_scope(
    service: DomainService, user: User, project: Project, scope_table: str, scope_uid: str | None
) -> None:
    if scope_table == "project":
        if scope_uid is not None:
            raise ApiException.BadRequest_400()
        return
    if scope_uid is None:
        raise ApiException.BadRequest_400()

    scope_id = _decode_socket_uid(scope_uid)
    if scope_table == "project_column":
        scope = service.project_column.get_by_id_like(scope_id)
    elif scope_table == "card":
        scope = service.card.get_by_id_like(scope_id)
    elif scope_table == "project_wiki":
        if not is_subscription_authorized(service, user, SocketTopic.BoardWikiPrivate, scope_uid):
            raise ApiException.Forbidden_403()
        scope = service.project_wiki.get_by_id_like(scope_id)
    else:
        raise ApiException.BadRequest_400()
    if not scope or scope.project_id != project.id:
        raise ApiException.Forbidden_403()


def _authorize_board_chat_permission_level(
    service: DomainService,
    user: User,
    project: Project,
    permission_level: object,
    actions: list[str] | None = None,
) -> None:
    if permission_level == "read":
        return
    if permission_level not in {"edit", "full_access"}:
        raise ApiException.Forbidden_403()

    current_actions = (
        actions if actions is not None else service.project.get_user_role_actions_by_project(user, project)
    )
    if ALL_GRANTED not in current_actions and ProjectRoleAction.Update.value not in current_actions:
        raise ApiException.Forbidden_403()


def _authorize_board_chat_run_lease(service: DomainService, project_uid: str, run: InternalBotRun) -> None:
    project = service.project.get_by_id_like(_decode_socket_uid(project_uid))
    user = Auth.get_user_by_id(int(run.user_id))
    if (
        project is None
        or not isinstance(user, User)
        or user.deleted_at is not None
        or user.activated_at is None
        or run.project_id != project.id
        or not is_subscription_authorized(service, user, SocketTopic.Board, project_uid)
    ):
        raise ApiException.Forbidden_403()

    scope_table = getattr(run, "scope_table", "project")
    scope_uid = getattr(run, "scope_uid", None)
    _authorize_board_chat_scope(service, user, project, scope_table, scope_uid)

    actions = service.project.get_user_role_actions_by_project(user, project)
    if scope_table == "card" and ALL_GRANTED not in actions and ProjectRoleAction.Read.value not in actions:
        raise ApiException.Forbidden_403()

    request_payload = getattr(run, "request_payload", {})
    permission_level = (
        request_payload.get("api_permission_level", "read") if isinstance(request_payload, dict) else None
    )
    _authorize_board_chat_permission_level(service, user, project, permission_level, actions)


@AppRouter.api.post("/auth/socket/board/{project_uid}/chat/runs", tags=["Auth"])
def accept_socket_board_chat_run(
    request: Request,
    project_uid: str,
    form: SocketBoardChatRunForm,
    service: DomainService = DomainService.scope(),
) -> JsonResponse:
    _authenticate_internal_socket(request)
    user = _authenticate_socket_user(request)
    if not is_subscription_authorized(service, user, SocketTopic.Board, project_uid):
        raise ApiException.Forbidden_403()

    project = service.project.get_by_id_like(_decode_socket_uid(project_uid))
    if not project:
        raise ApiException.Forbidden_403()
    bot_assignment = service.project.get_assigned_internal_bot_by_type(project, InternalBotType.ProjectChat)
    if not bot_assignment:
        raise ApiException.ServiceUnavailable_503()
    bot, _ = bot_assignment
    if (bot.platform, bot.platform_running_type) not in (
        (BotPlatform.Default, BotPlatformRunningType.Default),
        (BotPlatform.Langflow, BotPlatformRunningType.Endpoint),
    ):
        raise ApiException.ServiceUnavailable_503()

    _authorize_board_chat_scope(service, user, project, form.scope_table, form.scope_uid)
    _authorize_board_chat_permission_level(service, user, project, form.api_permission_level)

    attachment: dict[str, str] | None = None
    attachment_ticket = None
    file_token = form.file_token
    if file_token:
        attachment_ticket = get_board_chat_attachment_ticket(file_token)
        if (
            attachment_ticket is None
            or attachment_ticket.get("user_id") != int(user.id)
            or attachment_ticket.get("project_id") != int(project.id)
            or attachment_ticket.get("bot_id") != int(bot.id)
            or attachment_ticket.get("task_id") != str(form.task_id)
            or not all(isinstance(attachment_ticket.get(key), str) for key in ("file_id", "path"))
        ):
            raise ApiException.NotFound_404(ApiErrorCode.NF2021)
        attachment = {
            "file_id": attachment_ticket["file_id"],
            "path": attachment_ticket["path"],
            "token": file_token,
        }

    try:
        run, accepted, chat_session, project_session, user_message = service.internal_bot_run.accept_board_chat(
            task_id=form.task_id,
            user_id=user.id,
            project_id=project.id,
            internal_bot_id=bot.id,
            project_chat_session_id=_decode_socket_uid(form.session_uid) if form.session_uid else None,
            message=form.message,
            permission_level=form.api_permission_level,
            scope_table=form.scope_table,
            scope_uid=form.scope_uid,
            attachment=attachment,
        )
    except ValueError as error:
        raise ApiException.Conflict_409() from error
    except PermissionError as error:
        raise ApiException.Forbidden_403() from error
    if attachment_ticket is not None and file_token is not None:
        set_board_chat_attachment_ticket(
            file_token,
            {**attachment_ticket, "run_uid": run.get_uid()},
        )
    return JsonResponse(
        {
            "run_uid": run.get_uid(),
            "status": run.status.value,
            "accepted": accepted,
            "session": {**chat_session.api_response(), **project_session.api_response()},
            "user_message": {**user_message.api_response(), "chat_session_uid": project_session.get_uid()},
        }
    )


@AppRouter.api.post("/auth/socket/board/{project_uid}/chat/cancel", tags=["Auth"])
def cancel_socket_board_chat_run(
    request: Request,
    project_uid: str,
    form: SocketBoardChatCancelForm,
    service: DomainService = DomainService.scope(),
) -> JsonResponse:
    _authenticate_internal_socket(request)
    user = _authenticate_socket_user(request)
    if not is_subscription_authorized(service, user, SocketTopic.Board, project_uid):
        raise ApiException.Forbidden_403()

    run = service.internal_bot_run.cancel_board_chat(form.task_id, user.id, _decode_socket_uid(project_uid))
    if run is None:
        raise ApiException.Conflict_409()
    _cleanup_board_chat_attachment(service, run, delete_external=True)
    return JsonResponse({"run_uid": run.get_uid(), "status": run.status.value, "task_id": run.client_task_id})


@AppRouter.api.get("/auth/socket/board/chat/runs/accepted", tags=["Auth"])
def list_accepted_socket_board_chat_runs(
    request: Request,
    limit: int = Query(default=100, ge=1, le=100),
    service: DomainService = DomainService.scope(),
    after_run_uid: str | None = None,
) -> JsonResponse:
    _authenticate_internal_socket(request)
    after_id = _decode_socket_uid(after_run_uid) if after_run_uid else None
    runs = service.internal_bot_run.list_accepted_board_chat_runs(limit, after_id)
    return JsonResponse(
        {
            "runs": [
                {
                    "run_uid": run.get_uid(),
                    "project_uid": run.project_id.to_short_code(),
                    "scope_table": run.scope_table,
                    "scope_uid": run.scope_uid,
                }
                for run in runs
            ]
        }
    )


def _board_chat_document_schema(document_type: EEditorCollaborationType, section: str | None) -> dict[str, str]:
    if document_type == EEditorCollaborationType.BoardColumnName:
        return {"api_field": "name", "field": "name"}
    if document_type == EEditorCollaborationType.Card:
        fields = {
            "title": {"api_field": "title", "field": "title"},
            "description": {"api_field": "description"},
            "deadline": {"api_field": "deadline_at", "field": "value"},
            "members": {"api_field": "assigned_users", "field": "selected-member-uids"},
            "labels": {"api_field": "labels", "field": "selected-label-uids"},
            "relationships-parents": {"api_field": "relationships", "field": "selected-relationships"},
            "relationships-children": {"api_field": "relationships", "field": "selected-relationships"},
        }
        if section is not None and section in fields:
            return fields[section]
        if section and section.startswith("attachment-"):
            return {"api_field": "attachment_name", "field": "name"}
        if section and section.startswith("comment-"):
            return {"api_field": "content"}
        if section and section.startswith("checkitem-") and section.endswith("-deadline"):
            return {"api_field": "deadline_at", "field": "value"}
        if section and (section.startswith("checklist-") or section.startswith("checkitem-")):
            return {"api_field": "title", "field": "title"}
        if section and section.startswith("metadata-"):
            return {"api_field": "metadata", "field": "key/value"}
    if document_type == EEditorCollaborationType.Wiki:
        fields = {
            "title": {"api_field": "title", "field": "title"},
            "content": {"api_field": "content"},
            "private-assignees": {"api_field": "assignees", "field": "selected-member-uids"},
        }
        if section is not None and section in fields:
            return fields[section]
        if section and section.startswith("metadata-"):
            return {"api_field": "metadata", "field": "key/value"}
    if document_type == EEditorCollaborationType.BotSchedule:
        return {"api_field": "schedule", "field": "schedule"}
    return {}


def _board_chat_active_documents(
    form: SocketBoardChatStartForm, run: InternalBotRun, project_uid: str
) -> list[dict[str, Any]]:
    documents: list[dict[str, Any]] = []
    for document_name in dict.fromkeys(form.active_document_names):
        parts = document_name.split(":")
        if len(parts) not in {2, 3} or any(not part for part in parts):
            raise ApiException.BadRequest_400()
        try:
            document_type = EEditorCollaborationType(parts[0])
        except ValueError as error:
            raise ApiException.BadRequest_400() from error
        entity_uid = parts[1]
        section = parts[2] if len(parts) == 3 else None

        if run.scope_table == "card":
            in_scope = (document_type == EEditorCollaborationType.Card and entity_uid == run.scope_uid) or (
                document_type == EEditorCollaborationType.BotSchedule
                and entity_uid == project_uid
                and bool(section and section.startswith(f"card-{run.scope_uid}-"))
            )
        elif run.scope_table == "project_column":
            in_scope = (
                document_type == EEditorCollaborationType.BoardColumnName
                and entity_uid == project_uid
                and section == run.scope_uid
            ) or (
                document_type == EEditorCollaborationType.BotSchedule
                and entity_uid == project_uid
                and bool(section and section.startswith(f"project_column-{run.scope_uid}-"))
            )
        elif run.scope_table == "project_wiki":
            in_scope = document_type == EEditorCollaborationType.Wiki and entity_uid == run.scope_uid
        else:
            in_scope = False

        if not in_scope:
            raise ApiException.Forbidden_403()
        document: dict[str, Any] = {
            "document_name": document_name,
            "entity_uid": entity_uid,
            "type": document_type.value,
            **_board_chat_document_schema(document_type, section),
        }
        if section is not None:
            document["section"] = section
        documents.append(document)
    return documents


@AppRouter.api.post("/auth/socket/board/{project_uid}/chat/runs/{run_uid}/start", tags=["Auth"])
def start_socket_board_chat_run(
    request: Request,
    project_uid: str,
    run_uid: str,
    form: SocketBoardChatStartForm,
    service: DomainService = DomainService.scope(),
) -> JsonResponse:
    _authenticate_internal_socket(request)
    user = _authenticate_socket_user(request)
    return _start_authorized_socket_board_chat_run(user, project_uid, run_uid, form, service)


@AppRouter.api.post("/auth/socket/board/{project_uid}/chat/runs/{run_uid}/recover-start", tags=["Auth"])
def recover_start_socket_board_chat_run(
    request: Request,
    project_uid: str,
    run_uid: str,
    form: SocketBoardChatStartForm,
    service: DomainService = DomainService.scope(),
) -> JsonResponse:
    _authenticate_internal_socket(request)
    run = service.internal_bot_run.get_board_chat_run(_decode_socket_uid(run_uid))
    if run is None or run.project_id != _decode_socket_uid(project_uid):
        raise ApiException.Forbidden_403()
    user = Auth.get_user_by_id(int(run.user_id))
    if not isinstance(user, User) or user.deleted_at is not None or user.activated_at is None:
        raise ApiException.Forbidden_403()
    return _start_authorized_socket_board_chat_run(user, project_uid, run_uid, form, service)


def _start_authorized_socket_board_chat_run(
    user: User,
    project_uid: str,
    run_uid: str,
    form: SocketBoardChatStartForm,
    service: DomainService,
) -> JsonResponse:
    if not is_subscription_authorized(service, user, SocketTopic.Board, project_uid):
        raise ApiException.Forbidden_403()

    project = service.project.get_by_id_like(_decode_socket_uid(project_uid))
    context = service.internal_bot_run.get_board_chat_context(_decode_socket_uid(run_uid))
    if not project or not context:
        raise ApiException.Forbidden_403()
    run, project_session, _ = context
    if run.user_id != user.id or run.project_id != project.id:
        raise ApiException.Forbidden_403()
    if run.status != InternalBotRunStatus.Accepted:
        raise ApiException.Conflict_409()
    _authorize_board_chat_scope(service, user, project, run.scope_table, run.scope_uid)
    request_payload = getattr(run, "request_payload", {})
    permission_level = (
        request_payload.get("api_permission_level", "read") if isinstance(request_payload, dict) else None
    )
    _authorize_board_chat_permission_level(service, user, project, permission_level)

    assignment = service.project.get_assigned_internal_bot_by_type(project, InternalBotType.ProjectChat)
    if not assignment:
        raise ApiException.ServiceUnavailable_503()
    bot, bot_assignment = assignment
    if bot.id != run.internal_bot_id or (bot.platform, bot.platform_running_type) not in (
        (BotPlatform.Default, BotPlatformRunningType.Default),
        (BotPlatform.Langflow, BotPlatformRunningType.Endpoint),
    ):
        raise ApiException.ServiceUnavailable_503()

    active_documents = _board_chat_active_documents(form, run, project_uid)
    scope_context = None
    if run.scope_table == "card":
        if run.scope_uid is None:
            raise ApiException.Forbidden_403()
        actions = service.project.get_user_role_actions_by_project(user, project)
        if ALL_GRANTED not in actions and ProjectRoleAction.Read.value not in actions:
            raise ApiException.Forbidden_403()
        try:
            scope_context = get_card_bundle(
                NativeCardWorkspaceAdapter(user, service),
                project_uid,
                run.scope_uid,
                CommentPage(),
                SectionPage(),
                [
                    CardBundleInclude.Description,
                    CardBundleInclude.People,
                    CardBundleInclude.Classification,
                    CardBundleInclude.Checklists,
                    CardBundleInclude.Attachments,
                    CardBundleInclude.Metadata,
                ],
            ).model_dump(mode="json")
        except ValueError as error:
            raise ApiException.Forbidden_403() from error

    try:
        started = service.internal_bot_run.start_board_chat(
            run.id,
            bot,
            user,
            bot_assignment,
            project_session,
            scope_context=scope_context,
            active_collaborative_documents=active_documents,
            lease_seconds=Env.AI_REQUEST_TIMEOUT + 30,
        )
    except (ValueError, RuntimeError) as error:
        raise ApiException.ServiceUnavailable_503() from error
    if started is None:
        raise ApiException.Conflict_409()
    claimed, bot_request, ai_message = started
    request_key = "langflow_request" if bot.platform == BotPlatform.Langflow else "graph_request"
    return JsonResponse(
        {
            "run_uid": claimed.get_uid(),
            "attempt": claimed.attempt,
            request_key: bot_request,
            "ai_message": {**ai_message.api_response(), "chat_session_uid": project_session.get_uid()},
        }
    )


@AppRouter.api.post("/auth/socket/board/{project_uid}/chat/runs/{run_uid}/finish", tags=["Auth"])
def finish_socket_board_chat_run(
    request: Request,
    project_uid: str,
    run_uid: str,
    form: SocketBoardChatFinishForm,
    service: DomainService = DomainService.scope(),
) -> JsonResponse:
    _authenticate_internal_socket(request)
    run_id = _decode_socket_uid(run_uid)
    run = service.internal_bot_run.get_board_chat_run(run_id)
    if run is None or run.project_id != _decode_socket_uid(project_uid):
        raise ApiException.Forbidden_403()

    run_status = InternalBotRunStatus(form.status)
    if not service.internal_bot_run.finish_board_chat(
        run_id, form.attempt, run_status, form.output_text, form.error_message
    ):
        raise ApiException.Conflict_409()
    _cleanup_board_chat_attachment(service, run, delete_external=run_status != InternalBotRunStatus.Completed)
    return JsonResponse({"run_uid": run_uid, "attempt": form.attempt, "status": run_status.value})


@AppRouter.api.post("/auth/socket/board/{project_uid}/chat/runs/{run_uid}/lease", tags=["Auth"])
def renew_socket_board_chat_run_lease(
    request: Request,
    project_uid: str,
    run_uid: str,
    form: SocketBoardChatLeaseForm,
    service: DomainService = DomainService.scope(),
) -> JsonResponse:
    _authenticate_internal_socket(request)
    run_id = _decode_socket_uid(run_uid)
    run = service.internal_bot_run.get_board_chat_run(run_id)
    if run is None or run.project_id != _decode_socket_uid(project_uid):
        raise ApiException.Forbidden_403()
    _authorize_board_chat_run_lease(service, project_uid, run)
    if run.status not in (InternalBotRunStatus.Streaming, InternalBotRunStatus.Resuming):
        raise ApiException.Conflict_409()
    if not service.internal_bot_run.renew_board_chat_lease(run_id, form.attempt, Env.AI_REQUEST_TIMEOUT + 30):
        raise ApiException.Conflict_409()
    return JsonResponse({"run_uid": run_uid, "attempt": form.attempt, "status": run.status.value})


@AppRouter.api.post("/auth/socket/board/{project_uid}/chat/runs/{run_uid}/pause", tags=["Auth"])
def pause_socket_board_chat_run(
    request: Request,
    project_uid: str,
    run_uid: str,
    form: SocketBoardChatPauseForm,
    service: DomainService = DomainService.scope(),
) -> JsonResponse:
    _authenticate_internal_socket(request)
    run_id = _decode_socket_uid(run_uid)
    project_id = _decode_socket_uid(project_uid)
    run = service.internal_bot_run.get_board_chat_run(run_id)
    if run is None or run.project_id != project_id:
        raise ApiException.Forbidden_403()
    project = service.project.get_by_id_like(project_id)
    if project is None:
        raise ApiException.Forbidden_403()

    try:
        paused = service.internal_bot_run.pause_board_chat(run_id, form.attempt, form.output_text, form.interrupt)
    except ValueError as error:
        raise ApiException.BadRequest_400() from error
    if paused is None:
        raise ApiException.Conflict_409()
    saved_interrupt, approval = paused
    if approval is not None:
        try:
            GraphApprovalPublisher.requested(project, service.graph_approval_request.get_api_response(approval))
        except Exception:
            Logger.main.exception("Failed to publish a persisted Board chat Graph approval")
    return JsonResponse(
        {
            "run_uid": run_uid,
            "attempt": form.attempt,
            "status": InternalBotRunStatus.AwaitingApproval.value,
            "interrupt": saved_interrupt,
        }
    )


def _get_authorized_project_chat_session(
    user: User, project_uid: str, session_uid: str, service: DomainService
) -> ChatSession:
    if not is_subscription_authorized(service, user, SocketTopic.Board, project_uid):
        raise ApiException.Forbidden_403()

    session = service.chat.get_session_by_filterable(ProjectChatSession, _decode_socket_uid(session_uid), project_uid)
    if not session or session[0].user_id != user.id:
        raise ApiException.Forbidden_403()
    return session[0]


@AppRouter.api.get("/auth/socket/board/{project_uid}/chat/session/{session_uid}", tags=["Auth"])
def authorize_socket_project_chat_session(
    request: Request,
    project_uid: str,
    session_uid: str,
    service: DomainService = DomainService.scope(),
) -> JsonResponse:
    _get_authorized_project_chat_session(_authenticate_socket_user(request), project_uid, session_uid, service)
    return JsonResponse()


@AppRouter.api.post("/auth/socket/board/{project_uid}/chat/session/{session_uid}/resume", tags=["Auth"])
def authorize_socket_project_chat_resume(
    request: Request,
    project_uid: str,
    session_uid: str,
    form: SocketChatResumeAuthorizationForm,
    service: DomainService = DomainService.scope(),
) -> JsonResponse:
    chat_session = _get_authorized_project_chat_session(
        _authenticate_socket_user(request), project_uid, session_uid, service
    )
    history = service.chat.get_history_by_id_like(_decode_socket_uid(form.message_uid))
    if not history or history.chat_session_id != chat_session.id or not history.is_received:
        raise ApiException.Forbidden_403()

    interrupt = history.message.graph_interrupt
    if not isinstance(interrupt, dict):
        raise ApiException.Forbidden_403()
    value = interrupt.get("value")
    interrupt_value = value if isinstance(value, dict) else interrupt
    if (
        interrupt_value.get("thread_id") != form.thread_id
        or interrupt_value.get("session_id") != form.session_id
        or interrupt_value.get("status") not in (None, "pending")
    ):
        raise ApiException.Forbidden_403()

    approval_uid = interrupt_value.get("approval_uid")
    if approval_uid is not None:
        if not isinstance(approval_uid, str) or approval_uid != form.approval_uid:
            raise ApiException.Forbidden_403()
        approval_id = _decode_socket_uid(approval_uid)
        if not service.graph_approval_request.is_pending_chat_resume(
            approval_id, chat_session, history, form.thread_id
        ):
            raise ApiException.Forbidden_403()
    elif form.approval_uid or interrupt_value.get("type") == "approval_request":
        raise ApiException.Forbidden_403()

    return JsonResponse()


@AppRouter.api.post("/auth/socket/board/{project_uid}/chat/resume/claim", tags=["Auth"])
def claim_socket_board_chat_resume(
    request: Request,
    project_uid: str,
    form: SocketBoardChatResumeClaimForm,
    service: DomainService = DomainService.scope(),
) -> JsonResponse:
    _authenticate_internal_socket(request)
    user = _authenticate_socket_user(request)
    if not is_subscription_authorized(service, user, SocketTopic.Board, project_uid):
        raise ApiException.Forbidden_403()

    project_id = _decode_socket_uid(project_uid)
    project = service.project.get_by_id_like(project_id)
    if project is None:
        raise ApiException.Forbidden_403()
    ai_message_id = _decode_socket_uid(form.message_uid)
    run = service.internal_bot_run.get_board_chat_run_by_ai_message(project_id, user.id, ai_message_id)
    if run is None or run.project_id != project_id or run.user_id != user.id or run.graph_session_id != form.session_id:
        raise ApiException.Forbidden_403()
    _authorize_board_chat_scope(service, user, project, run.scope_table, run.scope_uid)

    approval_id = _decode_socket_uid(form.approval_uid) if form.approval_uid else None
    if approval_id is not None:
        actions = service.project.get_user_role_actions_by_project(user, project)
        if ALL_GRANTED not in actions and ProjectRoleAction.Update.value not in actions:
            raise ApiException.Forbidden_403()

    resume = form.resume.model_dump(exclude_none=True)
    graph_resume = dict(resume)
    if form.resume.approved:
        graph_resume.update(
            app_api_token=AuthSecurity.create_bot_one_time_token(int(user.id), "full_access"),
            api_permission_level="full_access",
            api_approval_policy={permission.value: "allow" for permission in ApiPermission},
        )

    claimed = service.internal_bot_run.claim_board_chat_resume(
        project_id,
        user.id,
        ai_message_id,
        form.thread_id,
        form.session_id,
        approval_id,
        resume,
        Env.AI_REQUEST_TIMEOUT + 30,
    )
    if claimed is None:
        raise ApiException.Conflict_409()

    return JsonResponse(
        {
            "run_uid": claimed.get_uid(),
            "attempt": claimed.attempt,
            "thread_id": claimed.graph_thread_id,
            "session_id": claimed.graph_session_id,
            "resume": graph_resume,
        }
    )


@AppRouter.api.post("/auth/socket/board/{project_uid}/chat/runs/{run_uid}/resume/result", tags=["Auth"])
def complete_socket_board_chat_resume(
    request: Request,
    project_uid: str,
    run_uid: str,
    form: SocketBoardChatResumeResultForm,
    service: DomainService = DomainService.scope(),
) -> JsonResponse:
    _authenticate_internal_socket(request)
    run_id = _decode_socket_uid(run_uid)
    project_id = _decode_socket_uid(project_uid)
    run = service.internal_bot_run.get_board_chat_run(run_id)
    if run is None or run.project_id != project_id:
        raise ApiException.Forbidden_403()
    if run.graph_thread_id != form.thread_id or run.graph_session_id != form.session_id:
        raise ApiException.Conflict_409()
    project = service.project.get_by_id_like(project_id)
    if project is None:
        raise ApiException.Forbidden_403()

    try:
        result = service.internal_bot_run.complete_board_chat_resume(
            run_id, form.attempt, form.response_text, form.interrupt
        )
    except ValueError as error:
        raise ApiException.BadRequest_400() from error
    if result is None:
        raise ApiException.Conflict_409()
    saved_run, original_message, resumed_message, resolved_approval, requested_approval, newly_applied = result
    if newly_applied:
        for approval, publish in (
            (resolved_approval, GraphApprovalPublisher.updated),
            (requested_approval, GraphApprovalPublisher.requested),
        ):
            if approval is not None:
                try:
                    publish(project, service.graph_approval_request.get_api_response(approval))
                except Exception:
                    Logger.main.exception("Failed to publish a persisted Board chat Graph approval result")

    return JsonResponse(
        {
            "run_uid": run_uid,
            "attempt": form.attempt,
            "status": saved_run.status.value,
            "newly_applied": newly_applied,
            "original_message": {**original_message.api_response(), "chat_session_uid": form.session_id},
            "resumed_message": (
                {**resumed_message.api_response(), "chat_session_uid": form.session_id}
                if resumed_message is not None
                else None
            ),
        }
    )


@AppRouter.api.get("/auth/socket/board/{project_uid}/chat/availability", tags=["Auth"])
def get_socket_project_chat_availability(
    request: Request,
    project_uid: str,
    service: DomainService = DomainService.scope(),
) -> JsonResponse:
    user = _authenticate_socket_user(request)
    if not is_subscription_authorized(service, user, SocketTopic.Board, project_uid):
        raise ApiException.Forbidden_403()

    result = service.project.get_assigned_internal_bot_by_type(project_uid, InternalBotType.ProjectChat)
    if not result:
        return JsonResponse(content={"available": False, "bot": None})

    internal_bot, _ = result
    bot = internal_bot.api_response()
    for field in ("created_at", "updated_at"):
        bot[field] = (
            getattr(internal_bot, field)
            .astimezone(timezone.utc)
            .isoformat(timespec="milliseconds")
            .replace("+00:00", "Z")
        )
    headers = {"Accept": "application/json", "Content-Type": "application/json"}
    if internal_bot.platform == BotPlatform.Default:
        base_url = Env.DEFAULT_GRAPH_URL
    elif (
        internal_bot.platform == BotPlatform.Langflow
        and internal_bot.platform_running_type == BotPlatformRunningType.Endpoint
        and internal_bot.api_url
    ):
        base_url = internal_bot.api_url
        headers["X-API-KEY"] = internal_bot.api_key
    else:
        return JsonResponse(content={"available": False, "bot": bot})

    try:
        response = requests.get(f"{base_url.rstrip('/')}/health", headers=headers, timeout=Env.AI_REQUEST_TIMEOUT)
        available = response.status_code == status.HTTP_200_OK
    except requests.RequestException:
        available = False

    return JsonResponse(content={"available": available, "bot": bot})


@AppRouter.api.post("/auth/socket/editor-document", tags=["Auth"])
def authorize_socket_editor_document(
    request: Request,
    form: SocketEditorDocumentAuthorizationForm,
    service: DomainService = DomainService.scope(),
) -> JsonResponse:
    user = _authenticate_socket_user(request)
    subscription = authorized_editor_document_subscription(service, user, form.document_name)
    authorized = subscription is not None
    writable = bool(subscription and is_editor_document_write_authorized(service, user, subscription))
    return JsonResponse(
        {
            "authorized": authorized,
            "writable": writable,
            "user_name": user.get_fullname() if authorized else None,
        }
    )


@AppRouter.api.post("/auth/socket/editor-ai", tags=["Auth"])
def authorize_socket_editor_ai(
    request: Request,
    form: SocketEditorAiAuthorizationForm,
    service: DomainService = DomainService.scope(),
) -> JsonResponse:
    user = _authenticate_socket_user(request)
    _authorized_editor_ai_scope(user, form, service)
    return JsonResponse()


def _authorized_editor_ai_scope(
    user: User, form: SocketEditorAiAuthorizationForm, service: DomainService
) -> tuple[Project, str]:
    project = service.project.get_by_id_like(_decode_socket_uid(form.project_uid))
    subscription = authorized_editor_document_subscription(service, user, form.document_name)
    if not project or not subscription or subscription[1] != form.scope_uid:
        raise ApiException.Forbidden_403()

    scope_id = _decode_socket_uid(form.scope_uid)
    if subscription[0] == SocketTopic.BoardCard:
        scope = service.card.get_by_id_like(scope_id)
        scope_table = "card"
    elif subscription[0] == SocketTopic.BoardWikiPrivate:
        scope = service.project_wiki.get_by_id_like(scope_id)
        scope_table = "project_wiki"
    else:
        raise ApiException.Forbidden_403()

    if not scope or scope.project_id != project.id:
        raise ApiException.Forbidden_403()
    return project, scope_table


@AppRouter.api.post("/auth/socket/editor-ai/runs", tags=["Auth"])
def accept_socket_editor_run(
    request: Request,
    form: SocketEditorRunForm,
    service: DomainService = DomainService.scope(),
) -> JsonResponse:
    _authenticate_internal_socket(request)
    user = _authenticate_socket_user(request)
    project, scope_table = _authorized_editor_ai_scope(user, form, service)

    bot_type = InternalBotType(form.kind)
    bot_assignment = service.project.get_assigned_internal_bot_by_type(project, bot_type)
    if not bot_assignment:
        raise ApiException.ServiceUnavailable_503()
    bot, _assignment = bot_assignment
    if bot.platform != BotPlatform.Default or bot.platform_running_type != BotPlatformRunningType.Default:
        raise ApiException.ServiceUnavailable_503()

    try:
        run, accepted = service.internal_bot_run.accept_editor(
            kind=InternalBotRunKind(form.kind),
            task_id=form.task_id,
            user_id=user.id,
            project_id=project.id,
            internal_bot_id=bot.id,
            scope_table=scope_table,
            scope_uid=form.scope_uid,
            document_name=form.document_name,
            system=form.system,
            messages=[{"role": message.role, "content": message.content} for message in form.messages]
            if form.messages is not None
            else None,
            prompt=form.prompt,
        )
    except ValueError as error:
        raise ApiException.Conflict_409() from error
    return JsonResponse({"run_uid": run.get_uid(), "status": run.status.value, "accepted": accepted})


@AppRouter.api.get("/auth/socket/editor-ai/runs/accepted", tags=["Auth"])
def list_accepted_socket_editor_runs(
    request: Request,
    limit: int = Query(default=100, ge=1, le=100),
    service: DomainService = DomainService.scope(),
    after_run_uid: str | None = None,
) -> JsonResponse:
    _authenticate_internal_socket(request)
    after_id = _decode_socket_uid(after_run_uid) if after_run_uid else None
    runs = service.internal_bot_run.list_accepted_editor_runs(limit, after_id)
    return JsonResponse(
        {
            "runs": [
                {
                    "run_uid": run.get_uid(),
                    "project_uid": run.project_id.to_short_code(),
                    "task_id": run.client_task_id,
                    "kind": run.kind.value,
                }
                for run in runs
            ]
        }
    )


@AppRouter.api.post("/auth/socket/editor-ai/cancel", tags=["Auth"])
def cancel_socket_editor_run(
    request: Request,
    form: SocketEditorCancelForm,
    service: DomainService = DomainService.scope(),
) -> JsonResponse:
    _authenticate_internal_socket(request)
    user = _authenticate_socket_user(request)
    run = service.internal_bot_run.cancel_editor(
        InternalBotRunKind(form.kind), form.task_id, user.id, _decode_socket_uid(form.project_uid)
    )
    if run is None:
        raise ApiException.Conflict_409()
    return JsonResponse({"run_uid": run.get_uid(), "status": run.status.value, "task_id": run.client_task_id})


def _get_socket_editor_run(run_uid: str, service: DomainService) -> InternalBotRun:
    run = service.internal_bot_run.get_editor_run(_decode_socket_uid(run_uid))
    if run is None:
        raise ApiException.Forbidden_403()
    return run


def _get_authorized_editor_run_context(
    run: InternalBotRun, service: DomainService
) -> tuple[User, InternalBot, ProjectAssignedInternalBot]:
    if not run.scope_uid:
        raise ApiException.Forbidden_403()
    user = Auth.get_user_by_id(int(run.user_id))
    if not isinstance(user, User) or user.deleted_at is not None or user.activated_at is None:
        raise ApiException.Forbidden_403()

    document_name = run.request_payload.get("document_name")
    if not isinstance(document_name, str):
        raise ApiException.Forbidden_403()
    try:
        scope_form = SocketEditorAiAuthorizationForm(
            project_uid=run.project_id.to_short_code(),
            scope_uid=run.scope_uid,
            document_name=document_name,
        )
    except ValueError as error:
        raise ApiException.Forbidden_403() from error
    project, scope_table = _authorized_editor_ai_scope(user, scope_form, service)
    if project.id != run.project_id or scope_table != run.scope_table:
        raise ApiException.Forbidden_403()

    bot_assignment = service.project.get_assigned_internal_bot_by_type(project, InternalBotType(run.kind.value))
    if not bot_assignment:
        raise ApiException.ServiceUnavailable_503()
    bot, assignment = bot_assignment
    if (
        bot.id != run.internal_bot_id
        or bot.platform != BotPlatform.Default
        or bot.platform_running_type != BotPlatformRunningType.Default
    ):
        raise ApiException.ServiceUnavailable_503()
    return user, bot, assignment


@AppRouter.api.post("/auth/socket/editor-ai/status", tags=["Auth"])
def get_socket_editor_run_status(
    request: Request,
    form: SocketEditorStatusForm,
    service: DomainService = DomainService.scope(),
) -> JsonResponse:
    _authenticate_internal_socket(request)
    user = _authenticate_socket_user(request)
    project_id = _decode_socket_uid(form.project_uid)
    run = service.internal_bot_run.get_editor_run_by_task(
        InternalBotRunKind(form.kind), form.task_id, user.id, project_id
    )
    if run is None:
        raise ApiException.Forbidden_403()

    _get_authorized_editor_run_context(run, service)
    return JsonResponse(
        {
            "run_uid": run.get_uid(),
            "task_id": run.client_task_id,
            "kind": run.kind.value,
            "status": run.status.value,
            "attempt": run.attempt,
            "output_text": run.output_text,
            "error_message": run.error_message,
        }
    )


@AppRouter.api.post("/auth/socket/editor-ai/runs/{run_uid}/start", tags=["Auth"])
def start_socket_editor_run(
    request: Request,
    run_uid: str,
    service: DomainService = DomainService.scope(),
) -> JsonResponse:
    _authenticate_internal_socket(request)
    run = _get_socket_editor_run(run_uid, service)
    if run.status != InternalBotRunStatus.Accepted:
        raise ApiException.Conflict_409()
    user, bot, assignment = _get_authorized_editor_run_context(run, service)

    try:
        started = service.internal_bot_run.start_editor(run.id, bot, user, assignment, Env.AI_REQUEST_TIMEOUT + 30)
    except (ValueError, RuntimeError) as error:
        raise ApiException.ServiceUnavailable_503() from error
    if started is None:
        raise ApiException.Conflict_409()
    claimed, graph_request = started
    return JsonResponse({"run_uid": claimed.get_uid(), "attempt": claimed.attempt, "graph_request": graph_request})


@AppRouter.api.post("/auth/socket/editor-ai/runs/{run_uid}/finish", tags=["Auth"])
def finish_socket_editor_run(
    request: Request,
    run_uid: str,
    form: SocketBoardChatFinishForm,
    service: DomainService = DomainService.scope(),
) -> JsonResponse:
    _authenticate_internal_socket(request)
    run = _get_socket_editor_run(run_uid, service)
    run_status = InternalBotRunStatus(form.status)
    if run.status == InternalBotRunStatus.Resuming:
        if run_status != InternalBotRunStatus.Failed:
            raise ApiException.Conflict_409()
        result = service.internal_bot_run.fail_editor_resume(run.id, form.attempt, form.error_message or "")
        if result is None:
            raise ApiException.Conflict_409()
        saved_run, expired_approval, newly_applied = result
        if newly_applied and expired_approval is not None:
            project = service.project.get_by_id_like(run.project_id)
            if project is not None:
                try:
                    GraphApprovalPublisher.updated(
                        project, service.graph_approval_request.get_api_response(expired_approval)
                    )
                except Exception:
                    Logger.main.exception("Failed to publish a failed editor Graph approval result")
        return JsonResponse({"run_uid": run_uid, "attempt": form.attempt, "status": saved_run.status.value})
    if not service.internal_bot_run.finish_editor(
        run.id, form.attempt, run_status, form.output_text, form.error_message
    ):
        raise ApiException.Conflict_409()
    return JsonResponse({"run_uid": run_uid, "attempt": form.attempt, "status": run_status.value})


@AppRouter.api.post("/auth/socket/editor-ai/runs/{run_uid}/pause", tags=["Auth"])
def pause_socket_editor_run(
    request: Request,
    run_uid: str,
    form: SocketBoardChatPauseForm,
    service: DomainService = DomainService.scope(),
) -> JsonResponse:
    _authenticate_internal_socket(request)
    run = _get_socket_editor_run(run_uid, service)
    _get_authorized_editor_run_context(run, service)
    try:
        paused = service.internal_bot_run.pause_editor(run.id, form.attempt, form.output_text, form.interrupt)
    except ValueError as error:
        raise ApiException.BadRequest_400() from error
    if paused is None:
        raise ApiException.Conflict_409()
    saved_interrupt, approval = paused
    if approval is not None:
        project = service.project.get_by_id_like(run.project_id)
        if project is not None:
            try:
                GraphApprovalPublisher.requested(project, service.graph_approval_request.get_api_response(approval))
            except Exception:
                Logger.main.exception("Failed to publish a persisted editor Graph approval")
    return JsonResponse(
        {
            "run_uid": run_uid,
            "attempt": form.attempt,
            "status": InternalBotRunStatus.AwaitingApproval.value,
            "interrupt": saved_interrupt,
        }
    )


@AppRouter.api.post("/auth/socket/editor-ai/approvals/{approval_uid}/claim", tags=["Auth"])
def claim_socket_editor_resume(
    request: Request,
    approval_uid: str,
    form: SocketEditorResumeClaimForm,
    service: DomainService = DomainService.scope(),
) -> JsonResponse:
    _authenticate_internal_socket(request)
    approver = _authenticate_socket_user(request)
    project_id = _decode_socket_uid(form.project_uid)
    project = service.project.get_by_id_like(project_id)
    if project is None:
        raise ApiException.Forbidden_403()
    actions = service.project.get_user_role_actions_by_project(approver, project)
    if ALL_GRANTED not in actions and ProjectRoleAction.Update.value not in actions:
        raise ApiException.Forbidden_403()

    approval_id = _decode_socket_uid(approval_uid)
    run = service.internal_bot_run.get_editor_run_by_approval(approval_id)
    if run is None or run.project_id != project_id or run.status != InternalBotRunStatus.AwaitingApproval:
        raise ApiException.Conflict_409()
    _get_authorized_editor_run_context(run, service)

    decision = form.resume.model_dump(exclude_none=True)
    graph_resume = dict(decision)
    if form.resume.approved:
        graph_resume.update(
            app_api_token=AuthSecurity.create_bot_one_time_token(int(approver.id), "full_access"),
            api_permission_level="full_access",
            api_approval_policy={permission.value: "allow" for permission in ApiPermission},
        )
    claimed = service.internal_bot_run.claim_editor_resume(
        approval_id, project_id, approver.id, decision, Env.AI_REQUEST_TIMEOUT + 30
    )
    if claimed is None or not claimed.graph_thread_id or not claimed.graph_session_id:
        raise ApiException.Conflict_409()
    return JsonResponse(
        {
            "run_uid": claimed.get_uid(),
            "attempt": claimed.attempt,
            "thread_id": claimed.graph_thread_id,
            "session_id": claimed.graph_session_id,
            "resume": graph_resume,
        }
    )


@AppRouter.api.post("/auth/socket/editor-ai/runs/{run_uid}/resume/result", tags=["Auth"])
def complete_socket_editor_resume(
    request: Request,
    run_uid: str,
    form: SocketBoardChatResumeResultForm,
    service: DomainService = DomainService.scope(),
) -> JsonResponse:
    _authenticate_internal_socket(request)
    run = _get_socket_editor_run(run_uid, service)
    if run.graph_thread_id != form.thread_id or run.graph_session_id != form.session_id:
        raise ApiException.Conflict_409()
    try:
        result = service.internal_bot_run.complete_editor_resume(
            run.id, form.attempt, form.response_text, form.interrupt
        )
    except ValueError as error:
        raise ApiException.BadRequest_400() from error
    if result is None:
        raise ApiException.Conflict_409()
    saved_run, resolved_approval, requested_approval, newly_applied = result
    if newly_applied:
        project = service.project.get_by_id_like(run.project_id)
        if project is not None:
            for approval, publish in (
                (resolved_approval, GraphApprovalPublisher.updated),
                (requested_approval, GraphApprovalPublisher.requested),
            ):
                if approval is not None:
                    try:
                        publish(project, service.graph_approval_request.get_api_response(approval))
                    except Exception:
                        Logger.main.exception("Failed to publish a persisted editor Graph approval result")
    return JsonResponse(
        {
            "run_uid": run_uid,
            "attempt": form.attempt,
            "status": saved_run.status.value,
            "newly_applied": newly_applied,
            "output_text": saved_run.output_text,
        }
    )


@AppRouter.api.post("/auth/socket/editor-ai/runs/{run_uid}/lease", tags=["Auth"])
def renew_socket_editor_run_lease(
    request: Request,
    run_uid: str,
    form: SocketBoardChatLeaseForm,
    service: DomainService = DomainService.scope(),
) -> JsonResponse:
    _authenticate_internal_socket(request)
    run = _get_socket_editor_run(run_uid, service)
    if run.status != InternalBotRunStatus.Streaming:
        raise ApiException.Conflict_409()
    _get_authorized_editor_run_context(run, service)
    if not service.internal_bot_run.renew_editor_lease(run.id, form.attempt, Env.AI_REQUEST_TIMEOUT + 30):
        raise ApiException.Conflict_409()
    return JsonResponse({"run_uid": run_uid, "attempt": form.attempt, "status": run.status.value})


@AppRouter.api.post("/auth/socket/editor-ai/runs/{run_uid}/resume/lease", tags=["Auth"])
def renew_socket_editor_resume_lease(
    request: Request,
    run_uid: str,
    form: SocketBoardChatLeaseForm,
    service: DomainService = DomainService.scope(),
) -> JsonResponse:
    _authenticate_internal_socket(request)
    run = _get_socket_editor_run(run_uid, service)
    if run.status != InternalBotRunStatus.Resuming:
        raise ApiException.Conflict_409()
    _get_authorized_editor_run_context(run, service)
    if not service.internal_bot_run.renew_editor_lease(run.id, form.attempt, Env.AI_REQUEST_TIMEOUT + 30):
        raise ApiException.Conflict_409()
    return JsonResponse({"run_uid": run_uid, "attempt": form.attempt, "status": run.status.value})


@AppRouter.api.post("/auth/socket/editor-http-document", tags=["Auth"])
def authorize_socket_editor_http_document(
    request: Request,
    form: SocketEditorDocumentAuthorizationForm,
    service: DomainService = DomainService.scope(),
) -> JsonResponse:
    user = _authenticate_editor_http_user(request)
    subscription = authorized_editor_document_subscription(service, user, form.document_name)
    authorized = subscription is not None and (
        not form.write or is_editor_document_write_authorized(service, user, subscription)
    )
    return JsonResponse({"authorized": authorized})


@AppRouter.api.post("/auth/socket/editor-http-documents", tags=["Auth"])
def authorize_socket_editor_http_documents(
    request: Request,
    form: SocketEditorDocumentsAuthorizationForm,
    service: DomainService = DomainService.scope(),
) -> JsonResponse:
    user = _authenticate_editor_http_user(request)
    authorized = True
    for name in dict.fromkeys(form.document_names):
        subscription = authorized_editor_document_subscription(service, user, name)
        if subscription is None or (
            form.write and not is_editor_document_write_authorized(service, user, subscription)
        ):
            authorized = False
            break
    return JsonResponse({"authorized": authorized})
