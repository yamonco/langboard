from json import JSONDecodeError
from json import loads as json_loads
from typing import Any, Literal
from pydantic import TypeAdapter, ValidationError
from ..core.routing import ApiPermission, EEditorCollaborationType
from ..core.security import AuthSecurity
from ..domain.models.ApiComfortTool import ApiComfortToolMap
from ..domain.models.BaseBotModel import BotPlatform, BotPlatformRunningType
from ..domain.models.InternalBot import InternalBot, InternalBotType
from ..domain.models.InternalBotRun import InternalBotRun, InternalBotRunKind, InternalBotRunStatus
from ..domain.models.ProjectAssignedInternalBot import ProjectAssignedInternalBot
from ..domain.models.ProjectChatSession import ProjectChatSession
from ..domain.models.User import User
from ..Env import Env
from ..helpers.AgentApiPermissionHelper import AGENT_PERMISSION_LEVEL_PERMISSIONS
from ..helpers.ApiComfortToolHelper import create_api_comfort_tool_prompt, expand_api_names_with_comfort_tools
from .TweaksComponent import LangboardCalledAPIToolsComponent, LangboardCalledVariablesComponent


_comfort_tool_adapter = TypeAdapter(ApiComfortToolMap)


def build_internal_bot_graph_request(
    bot: InternalBot,
    user: User,
    message: str,
    session_id: str,
    project_uid: str | None,
    rest_data: dict[str, Any],
    *,
    assignment: ProjectAssignedInternalBot | None = None,
    run_id: str | None = None,
    thread_scope: Literal["run", "session"] = "run",
    tweaks: dict[str, Any] | None = None,
    file_path: str | None = None,
) -> dict[str, Any]:
    if bot.platform != BotPlatform.Default or bot.platform_running_type != BotPlatformRunningType.Default:
        raise ValueError("Internal bot does not use the default Graph platform")
    if not session_id or not user.id:
        raise ValueError("Internal bot Graph request is missing a user or session")

    try:
        bot_value = json_loads(bot.value or "{}")
    except (TypeError, JSONDecodeError) as error:
        raise ValueError("Internal bot Graph settings are invalid") from error
    if not isinstance(bot_value, dict):
        raise ValueError("Internal bot Graph settings are invalid")

    permission_level = rest_data.get("api_permission_level")
    if permission_level not in ("read", "edit", "full_access"):
        permission_level = "read"
    token = AuthSecurity.create_bot_one_time_token(int(user.id), permission_level)

    variables = LangboardCalledVariablesComponent(
        event="chat",
        app_api_token=token,
        current_runner_type="user",
        current_runner_data={"uid": user.get_uid()},
        project_uid=project_uid,
        rest_data=rest_data,
    )
    graph_tweaks = dict(tweaks or {})
    if file_path:
        graph_tweaks["LangboardFile"] = {"path": file_path}
    graph_tweaks.update(variables.to_tweaks())
    graph_tweaks.update(variables.to_data())

    agent_llm = bot_value.pop("agent_llm", "")
    configured_api_names = _string_list(bot_value.pop("api_names", []))
    configured_prompt = bot_value.pop("system_prompt", "")
    approval_request = bot_value.pop("approval_request", None)
    approval_policy = bot_value.pop("api_approval_policy", None)
    comfort_names = _string_list(bot_value.pop("comfort_tool_names", []))
    comfort_descriptions = _string_map(bot_value.pop("comfort_tool_descriptions", {}))
    comfort_tools = _comfort_tools(bot_value.pop("comfort_tool_definitions", {}))

    if bot_value.get("base_url") == "default":
        bot_value["base_url"] = Env.OLLAMA_API_URL

    prompt = assignment.prompt if assignment is not None and not assignment.use_default_prompt else configured_prompt
    if not isinstance(prompt, str):
        prompt = ""
    comfort_prompt = create_api_comfort_tool_prompt(comfort_names, comfort_descriptions, comfort_tools)
    if comfort_prompt:
        prompt = "\n\n".join(part for part in (prompt, comfort_prompt) if part)

    prompt_tweak = graph_tweaks.get("Prompt")
    if isinstance(prompt_tweak, dict):
        context_prompt = prompt_tweak.get("prompt")
        if isinstance(context_prompt, str) and context_prompt:
            prompt = "\n\n".join(part for part in (prompt, context_prompt) if part)

    api_names = expand_api_names_with_comfort_tools(configured_api_names, comfort_names, comfort_tools)
    if api_names:
        tools_component = LangboardCalledAPIToolsComponent(api_names=api_names)
        graph_tweaks["LangboardCalledVariablesComponent"]["api_names"] = api_names
        graph_tweaks.update(tools_component.to_tweaks())
        graph_tweaks.update(tools_component.to_data())

    graph_tweaks["Graph"] = {
        "agent_llm": agent_llm if isinstance(agent_llm, str) else "",
        "settings": bot_value,
        "system_prompt": prompt,
        "api_names": api_names,
    }
    request_approval_policy = rest_data.get("api_approval_policy")
    if isinstance(request_approval_policy, dict):
        graph_tweaks["Graph"]["api_approval_policy"] = request_approval_policy
    elif isinstance(approval_policy, dict):
        graph_tweaks["Graph"]["api_approval_policy"] = approval_policy
    if approval_request:
        graph_tweaks["Graph"]["approval_request"] = approval_request

    thread_parts = [bot.get_uid(), str(user.id), project_uid or "global", session_id]
    if thread_scope != "session":
        thread_parts.append(run_id or session_id)

    return {
        "input_value": message,
        "input_type": "chat",
        "output_type": "chat",
        "session": session_id,
        "session_id": session_id,
        "thread_id": ":".join(thread_parts),
        "run_type": "internal_bot",
        "uid": bot.get_uid(),
        "tweaks": graph_tweaks,
    }


def build_internal_bot_langflow_request(
    bot: InternalBot,
    user: User,
    message: str,
    session_id: str,
    project_uid: str,
    rest_data: dict[str, Any],
    file_path: str | None = None,
) -> dict[str, Any]:
    if bot.platform != BotPlatform.Langflow or bot.platform_running_type != BotPlatformRunningType.Endpoint:
        raise ValueError("Internal bot does not use the Langflow endpoint platform")
    if not session_id or not user.id or not bot.api_url or not bot.value:
        raise ValueError("Internal bot Langflow request is missing its user, session, or endpoint")

    permission_level = rest_data.get("api_permission_level")
    if permission_level not in ("read", "edit", "full_access"):
        raise ValueError("Internal bot Langflow permission level is invalid")
    token = AuthSecurity.create_bot_one_time_token(int(user.id), permission_level)
    variables = LangboardCalledVariablesComponent(
        event="chat",
        app_api_token=token,
        current_runner_type="user",
        current_runner_data={"uid": user.get_uid()},
        project_uid=project_uid,
        rest_data=rest_data,
    )
    tweaks: dict[str, Any] = {**variables.to_tweaks(), **variables.to_data()}
    if file_path:
        tweaks["LangboardFile"] = {"path": file_path}
    request_body = {
        "input_value": message,
        "input_type": "chat",
        "output_type": "chat",
        "session": session_id,
        "session_id": session_id,
        "run_type": "internal_bot",
        "uid": bot.get_uid(),
        "tweaks": tweaks,
    }
    return {
        "url": f"{bot.api_url.rstrip('/')}/{bot.value.lstrip('/')}?stream=true",
        "api_key": bot.api_key,
        "session_id": session_id,
        "thread_id": f"{bot.get_uid()}:{user.id}:{project_uid}:{session_id}",
        "request_body": request_body,
    }


def build_board_chat_bot_request(
    run: InternalBotRun,
    bot: InternalBot,
    user: User,
    project_session: ProjectChatSession,
    assignment: ProjectAssignedInternalBot,
    *,
    scope_context: dict[str, Any] | None,
    active_collaborative_documents: list[dict[str, Any]],
) -> dict[str, Any]:
    if (
        run.kind != InternalBotRunKind.BoardChat
        or run.status != InternalBotRunStatus.Streaming
        or run.attempt <= 0
        or run.user_id != user.id
        or run.internal_bot_id != bot.id
        or assignment.internal_bot_id != bot.id
        or assignment.project_id != run.project_id
        or run.chat_session_id is None
        or run.chat_history_id is None
        or project_session.chat_session_id != run.chat_session_id
        or project_session.project_id != run.project_id
    ):
        raise ValueError("Board chat run is not bound to the selected user, bot, and session")

    message = run.request_payload.get("message")
    permission_level = run.request_payload.get("api_permission_level")
    if not isinstance(message, str) or not isinstance(permission_level, str):
        raise ValueError("Board chat run payload is invalid")
    permissions = AGENT_PERMISSION_LEVEL_PERMISSIONS.get(permission_level)
    if permissions is None:
        raise ValueError("Board chat run payload is invalid")
    if "file_path" in run.request_payload:
        raise ValueError("Board chat attachment execution is not supported")
    attachment = run.request_payload.get("attachment")
    file_path: str | None = None
    if attachment is not None:
        if not isinstance(attachment, dict):
            raise ValueError("Board chat attachment payload is invalid")
        file_path = attachment.get("path")
        if not isinstance(file_path, str) or not file_path:
            raise ValueError("Board chat attachment payload is invalid")
        if bot.platform != BotPlatform.Langflow:
            raise ValueError("Board chat attachments are not supported by this bot")
    if not message and attachment is None:
        raise ValueError("Board chat run payload is empty")

    project_uid = run.project_id.to_short_code()
    rest_data: dict[str, Any] = {
        "project_uid": project_uid,
        "chat_scope": run.scope_table,
        "api_permission_level": permission_level,
        "api_approval_policy": {
            permission.value: "allow" if permission == ApiPermission.Read else "ask"
            for permission in ApiPermission
            if permission.value in permissions
        },
        "chat_session_uid": run.chat_session_id.to_short_code(),
        "project_chat_session_uid": project_session.get_uid(),
        "chat_history_uid": run.chat_history_id.to_short_code(),
    }

    scope_keys = {
        "project_column": "project_column_uid",
        "card": "card_uid",
        "project_wiki": "project_wiki_uid",
    }
    if run.scope_table == "project":
        if run.scope_uid is not None or scope_context is not None:
            raise ValueError("Project chat scope is invalid")
    else:
        scope_key = scope_keys.get(run.scope_table)
        if scope_key is None or not run.scope_uid:
            raise ValueError("Board chat scope is invalid")
        rest_data[scope_key] = run.scope_uid
        if run.scope_table == "card":
            if scope_context is None or scope_context.get("card_uid") != run.scope_uid:
                raise ValueError("Matching card chat context is required")
            rest_data["scope_context"] = scope_context
        elif scope_context is not None:
            raise ValueError("Board chat scope context is invalid")

    if active_collaborative_documents:
        rest_data["active_collaborative_documents"] = active_collaborative_documents
        rest_data["collaborative_edit_instruction"] = " ".join(
            [
                "Some fields in the current scope are being edited in real time.",
                "When changing one of those fields, use the normal matching edit API with the intended final field value.",
                "The API will automatically update the active collaborative draft instead of saving directly.",
                "Do not store unsaved draft values in metadata.",
            ]
        )

    if bot.platform == BotPlatform.Langflow:
        return build_internal_bot_langflow_request(
            bot, user, message, project_session.get_uid(), project_uid, rest_data, file_path
        )

    return build_internal_bot_graph_request(
        bot,
        user,
        message,
        project_session.get_uid(),
        project_uid,
        rest_data,
        assignment=assignment,
        run_id=run.client_task_id,
        thread_scope="session",
    )


def build_editor_graph_request(
    run: InternalBotRun,
    bot: InternalBot,
    user: User,
    assignment: ProjectAssignedInternalBot,
) -> dict[str, Any]:
    bot_types = {
        InternalBotRunKind.EditorChat: InternalBotType.EditorChat,
        InternalBotRunKind.EditorCopilot: InternalBotType.EditorCopilot,
    }
    document_types = {
        "card": (EEditorCollaborationType.Card.value, "card_uid"),
        "project_wiki": (EEditorCollaborationType.Wiki.value, "project_wiki_uid"),
    }
    if (
        bot_types.get(run.kind) != bot.bot_type
        or run.status != InternalBotRunStatus.Streaming
        or run.attempt <= 0
        or run.user_id != user.id
        or run.internal_bot_id != bot.id
        or assignment.internal_bot_id != bot.id
        or assignment.project_id != run.project_id
        or run.scope_table not in document_types
        or not run.scope_uid
        or not run.client_task_id
    ):
        raise ValueError("Editor AI run is not bound to the selected user, bot, and document")

    document_name = run.request_payload.get("document_name")
    system = run.request_payload.get("system", "")
    document_type, scope_key = document_types[run.scope_table]
    if (
        not isinstance(document_name, str)
        or not document_name.startswith(f"{document_type}:{run.scope_uid}:")
        or not isinstance(system, str)
        or run.request_payload.get("file_path") is not None
    ):
        raise ValueError("Editor AI run payload is invalid")

    if run.kind == InternalBotRunKind.EditorChat:
        messages = run.request_payload.get("messages")
        if not isinstance(messages, list) or not messages:
            raise ValueError("Editor AI run payload is invalid")
        parts: list[str] = []
        for entry in messages:
            if not isinstance(entry, dict):
                raise ValueError("Editor AI run payload is invalid")
            role = entry.get("role")
            content = entry.get("content")
            if role not in {"system", "user", "assistant"} or not isinstance(content, str):
                raise ValueError("Editor AI run payload is invalid")
            parts.append(f"{role}: {content}")
        message = "\n".join(parts)
    else:
        message = run.request_payload.get("prompt")
        if not isinstance(message, str) or not message:
            raise ValueError("Editor AI run payload is invalid")

    project_uid = run.project_id.to_short_code()
    session_id = f"{user.get_uid()}-{project_uid}"
    return build_internal_bot_graph_request(
        bot,
        user,
        message,
        session_id,
        project_uid,
        {
            "project_uid": project_uid,
            scope_key: run.scope_uid,
            "document_name": document_name,
            "origin_type": "editor",
        },
        assignment=assignment,
        run_id=run.client_task_id,
        tweaks={"Prompt": {"prompt": system}},
    )


def _string_list(value: object) -> list[str]:
    return [item for item in value if isinstance(item, str)] if isinstance(value, list) else []


def _string_map(value: object) -> dict[str, str]:
    if not isinstance(value, dict):
        return {}
    return {key: item for key, item in value.items() if isinstance(key, str) and isinstance(item, str)}


def _comfort_tools(value: object) -> dict[str, ApiComfortToolMap]:
    if not isinstance(value, dict):
        return {}
    tools: dict[str, ApiComfortToolMap] = {}
    for name, definition in value.items():
        if not isinstance(name, str):
            continue
        try:
            tools[name] = _comfort_tool_adapter.validate_python(definition)
        except ValidationError:
            continue
    return tools
