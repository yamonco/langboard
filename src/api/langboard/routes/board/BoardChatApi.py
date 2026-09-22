from uuid import UUID
from fastapi import Depends, File, Form, UploadFile, status
from langboard_shared.ai.BoardChatAttachment import (
    create_board_chat_attachment_token,
    delete_board_chat_attachment_ticket,
    schedule_board_chat_attachment_cleanup,
)
from langboard_shared.ai.LangflowFileClient import LangflowFileClient
from langboard_shared.core.filter import AuthFilter
from langboard_shared.core.logger import Logger
from langboard_shared.core.routing import (
    ApiErrorCode,
    ApiException,
    AppRouter,
    EEditorCollaborationType,
    JsonResponse,
    collaborative_block,
    collaborative_edit,
    collaborative_text,
    create_editor_collaboration_document_id,
)
from langboard_shared.core.routing.Exception import MissingException
from langboard_shared.core.schema import OpenApiSchema
from langboard_shared.domain.models import (
    ChatHistory,
    ChatSession,
    ChatTemplate,
    Project,
    ProjectChatSession,
    ProjectRole,
    User,
)
from langboard_shared.domain.models.BaseBotModel import BotPlatform, BotPlatformRunningType
from langboard_shared.domain.models.InternalBot import InternalBotType
from langboard_shared.domain.models.ProjectRole import ProjectRoleAction
from langboard_shared.domain.services import DomainService
from langboard_shared.Env import Env
from langboard_shared.filter import RoleFilter
from langboard_shared.publishers import ProjectPublisher
from langboard_shared.security import Auth, RoleFinder
from .forms import ChatHistoryPagination, CreateChatTemplate, UpdateChatTemplate, UpdateProjectChatSessionForm


_logger = Logger.use("board-chat-attachment-api")


@AppRouter.api.post(
    "/board/{project_uid}/chat/upload",
    tags=["Board.Chat"],
    responses=OpenApiSchema().auth().forbidden().err(404, ApiErrorCode.NF2001).err(406, ApiErrorCode.OP1002).get(),
)
@RoleFilter.add(ProjectRole, [ProjectRoleAction.Read], RoleFinder.project)
@AuthFilter.add("user")
def upload_project_chat_attachment(
    project_uid: str,
    task_id: UUID = Form(),
    attachment: UploadFile = File(),
    user: User = Auth.scope("user"),
    service: DomainService = DomainService.scope(),
) -> JsonResponse:
    if not attachment:
        raise MissingException("body", "attachment")
    if Env.CACHE_TYPE != "redis":
        raise ApiException.ServiceUnavailable_503()

    project = service.project.get_by_id_like(project_uid)
    if project is None:
        raise ApiException.NotFound_404(ApiErrorCode.NF2001)
    assignment = service.project.get_assigned_internal_bot_by_type(project, InternalBotType.ProjectChat)
    if assignment is None:
        raise ApiException.NotFound_404(ApiErrorCode.NF3004)
    bot, bot_assignment = assignment
    if (
        bot_assignment.project_id != project.id
        or bot.platform != BotPlatform.Langflow
        or bot.platform_running_type != BotPlatformRunningType.Endpoint
    ):
        raise ApiException.NotAcceptable_406(ApiErrorCode.OP1002)
    uploaded = None
    ticket_token = None
    try:
        uploaded = LangflowFileClient.upload(
            bot,
            attachment.file,
            attachment.filename or "",
            attachment.content_type,
            attachment.size,
        )
        ticket_token = create_board_chat_attachment_token(
            {
                "user_id": int(user.id),
                "project_id": int(project.id),
                "bot_id": int(bot.id),
                "task_id": str(task_id),
                "file_id": uploaded.file_id,
                "path": uploaded.path,
                "filename": attachment.filename or "",
            }
        )
        schedule_board_chat_attachment_cleanup(ticket_token)
    except Exception:
        external_deleted = uploaded is None
        if uploaded is not None:
            external_deleted = LangflowFileClient.delete(bot, uploaded.file_id)
        if ticket_token is not None and external_deleted:
            delete_board_chat_attachment_ticket(ticket_token)
        elif ticket_token is not None:
            try:
                schedule_board_chat_attachment_cleanup(ticket_token, 1)
            except Exception:
                _logger.exception("Could not schedule attachment cleanup after upload failure")
        _logger.exception("Board chat attachment upload failed")
        raise ApiException.NotAcceptable_406(ApiErrorCode.OP1002)
    return JsonResponse(content={"file_token": ticket_token}, status_code=status.HTTP_201_CREATED)


@AppRouter.api.get(
    "/board/{project_uid}/chat/sessions",
    tags=["Board.Chat"],
    responses=OpenApiSchema().suc({"sessions": [ChatSession]}).auth().forbidden().get(),
)
@RoleFilter.add(ProjectRole, [ProjectRoleAction.Read], RoleFinder.project)
@AuthFilter.add("user")
def get_project_chat_sessions(
    project_uid: str,
    user: User = Auth.scope("user"),
    service: DomainService = DomainService.scope(),
) -> JsonResponse:
    sessions = service.chat.get_api_session_list(user, ProjectChatSession, project_uid)

    return JsonResponse(content={"sessions": sessions})


@AppRouter.api.get(
    "/board/{project_uid}/chat/run/{task_id}",
    tags=["Board.Chat"],
    responses=OpenApiSchema().auth().forbidden().err(404, ApiErrorCode.NF2021).get(),
)
@RoleFilter.add(ProjectRole, [ProjectRoleAction.Read], RoleFinder.project)
@AuthFilter.add("user")
def get_project_chat_run(
    project_uid: str,
    task_id: UUID,
    user: User = Auth.scope("user"),
    service: DomainService = DomainService.scope(),
) -> JsonResponse:
    project = service.project.get_by_id_like(project_uid)
    if project is None:
        raise ApiException.NotFound_404(ApiErrorCode.NF2021)
    result = service.internal_bot_run.get_owned_board_chat_status(task_id, user.id, project.id)
    if result is None:
        raise ApiException.NotFound_404(ApiErrorCode.NF2021)

    run, project_session, user_message, ai_message = result
    session_uid = project_session.get_uid()
    return JsonResponse(
        content={
            "task_id": run.client_task_id,
            "status": run.status.value,
            "session_uid": session_uid,
            "user_message": {**user_message.api_response(), "chat_session_uid": session_uid},
            "ai_message": {**ai_message.api_response(), "chat_session_uid": session_uid} if ai_message else None,
            "ai_message_uid": run.ai_chat_history_id.to_short_code() if run.ai_chat_history_id else None,
        }
    )


@AppRouter.api.get(
    "/board/{project_uid}/chat/session/{session_uid}",
    tags=["Board.Chat"],
    responses=OpenApiSchema().suc({"histories": [ChatHistory]}).auth().forbidden().get(),
)
@RoleFilter.add(ProjectRole, [ProjectRoleAction.Read], RoleFinder.project)
@AuthFilter.add("user")
def get_project_chat_histories(
    project_uid: str,
    session_uid: str,
    query: ChatHistoryPagination = Depends(),
    user: User = Auth.scope("user"),
    service: DomainService = DomainService.scope(),
) -> JsonResponse:
    result = service.chat.get_session_by_filterable(ProjectChatSession, session_uid, project_uid)
    if not result or result[0].user_id != user.id:
        return JsonResponse(content={"histories": []})
    chat_session, session = result

    histories = service.chat.get_api_history_list(user, chat_session, ProjectChatSession, session, query)

    return JsonResponse(content={"histories": histories})


@AppRouter.api.put(
    "/board/{project_uid}/chat/session/{session_uid}",
    tags=["Board.Chat"],
    responses=OpenApiSchema().auth().forbidden().err(404, ApiErrorCode.NF2021).get(),
)
@RoleFilter.add(ProjectRole, [ProjectRoleAction.Read], RoleFinder.project)
@AuthFilter.add("user")
def update_project_chat_session(
    project_uid: str,
    session_uid: str,
    form: UpdateProjectChatSessionForm,
    user: User = Auth.scope("user"),
    service: DomainService = DomainService.scope(),
) -> JsonResponse:
    session = service.chat.get_session_by_filterable(ProjectChatSession, session_uid, project_uid)
    if not session or session[0].user_id != user.id:
        raise ApiException.NotFound_404(ApiErrorCode.NF2021)
    chat_session, _ = session

    service.chat.update_session(
        chat_session,
        title=form.title,
        api_permission_level=form.api_permission_level,
    )

    return JsonResponse()


@AppRouter.api.delete(
    "/board/{project_uid}/chat/session/{session_uid}",
    tags=["Board.Chat"],
    responses=OpenApiSchema().auth().forbidden().get(),
)
@RoleFilter.add(ProjectRole, [ProjectRoleAction.Read], RoleFinder.project)
@AuthFilter.add("user")
def delete_project_chat_session(
    project_uid: str,
    session_uid: str,
    user: User = Auth.scope("user"),
    service: DomainService = DomainService.scope(),
) -> JsonResponse:
    session = service.chat.get_session_by_filterable(ProjectChatSession, session_uid, project_uid)
    if not session or session[0].user_id != user.id:
        return JsonResponse(content={"histories": []})

    chat_session, _ = session

    service.chat.delete_session(chat_session)

    return JsonResponse()


@AppRouter.api.get(
    "/board/{project_uid}/chat/templates",
    tags=["Board.Chat"],
    responses=OpenApiSchema().suc({"templates": [ChatTemplate]}).auth().forbidden().get(),
)
@RoleFilter.add(ProjectRole, [ProjectRoleAction.Read], RoleFinder.project)
@AuthFilter.add("user")
def get_chat_templates(project_uid: str, service: DomainService = DomainService.scope()) -> JsonResponse:
    templates = service.chat.get_api_template_list(Project.__tablename__, project_uid)

    return JsonResponse(content={"templates": templates})


@AppRouter.api.post(
    "/board/{project_uid}/chat/template",
    tags=["Board.Chat"],
    responses=OpenApiSchema(201).suc({"template": ChatTemplate}).auth().forbidden().err(404, ApiErrorCode.NF2001).get(),
)
@RoleFilter.add(ProjectRole, [ProjectRoleAction.Update], RoleFinder.project)
@AuthFilter.add("user")
def create_chat_template(
    project_uid: str, form: CreateChatTemplate, service: DomainService = DomainService.scope()
) -> JsonResponse:
    project = service.project.get_by_id_like(project_uid)
    if not project:
        raise ApiException.NotFound_404(ApiErrorCode.NF2001)

    template = service.chat.create_template(project, form.name, form.template)

    ProjectPublisher.chat_template_created(project, {"template": template.api_response()})

    return JsonResponse(content={"template": template.api_response()}, status_code=status.HTTP_201_CREATED)


@collaborative_edit(
    collaborative_text(
        create_editor_collaboration_document_id(
            EEditorCollaborationType.BoardSettings, "{project_uid}", "chat-template-{template_uid}"
        ),
        "name",
        "name",
    ),
    collaborative_text(
        create_editor_collaboration_document_id(
            EEditorCollaborationType.BoardSettings, "{project_uid}", "chat-template-{template_uid}"
        ),
        "template",
        "template",
    ),
)
@AppRouter.api.put(
    "/board/{project_uid}/chat/template/{template_uid}",
    tags=["Board.Chat"],
    responses=OpenApiSchema().auth().forbidden().err(404, ApiErrorCode.NF2018).get(),
)
@RoleFilter.add(ProjectRole, [ProjectRoleAction.Update], RoleFinder.project)
@AuthFilter.add("user")
def update_chat_template(
    project_uid: str,
    template_uid: str,
    form: UpdateChatTemplate,
    service: DomainService = DomainService.scope(),
) -> JsonResponse:
    project = service.project.get_by_id_like(project_uid)
    if not project:
        raise ApiException.NotFound_404(ApiErrorCode.NF2018)

    result = service.chat.update_template(template_uid, form.name, form.template)
    if not result:
        raise ApiException.NotFound_404(ApiErrorCode.NF2018)

    if result is True:
        return JsonResponse()

    template, model = result
    ProjectPublisher.chat_template_updated(project, template, model)

    return JsonResponse()


@collaborative_edit(
    collaborative_block(
        create_editor_collaboration_document_id(
            EEditorCollaborationType.BoardSettings, "{project_uid}", "chat-template-{template_uid}"
        )
    )
)
@AppRouter.api.delete(
    "/board/{project_uid}/chat/template/{template_uid}",
    tags=["Board.Chat"],
    responses=OpenApiSchema().auth().forbidden().err(404, ApiErrorCode.NF2018).get(),
)
@RoleFilter.add(ProjectRole, [ProjectRoleAction.Update], RoleFinder.project)
@AuthFilter.add("user")
def delete_chat_template(
    project_uid: str, template_uid: str, service: DomainService = DomainService.scope()
) -> JsonResponse:
    project = service.project.get_by_id_like(project_uid)
    if not project:
        raise ApiException.NotFound_404(ApiErrorCode.NF2018)

    result = service.chat.delete_template(template_uid)
    if not result:
        raise ApiException.NotFound_404(ApiErrorCode.NF2018)

    ProjectPublisher.chat_template_deleted(project, template_uid)

    return JsonResponse()
