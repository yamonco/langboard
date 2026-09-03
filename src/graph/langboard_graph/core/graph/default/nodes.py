import asyncio
from json import dumps as json_dumps
from re import compile as re_compile
from re import sub as re_sub
from typing import Any, cast
import httpx
from langboard_shared.Env import Env
from langchain.chat_models.base import BaseChatModel, _ConfigurableModel
from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.tools import StructuredTool
from langgraph.types import interrupt
from .chat_model import create_default_chat_model
from .context import create_runtime_context_state
from .history import create_langboard_history_context_prompt
from .state import DefaultGraphState
from .tooling import (
    create_langboard_api_tool_approval_request,
    create_langboard_api_tool_context,
    create_langboard_context_prompt,
    create_langboard_event_input,
)


_LANGBOARD_RESPONSE_RULES = "\n".join(
    [
        "Langboard user-facing response rules:",
        "- Do not expose internal identifiers or raw API metadata in normal answers.",
        "- Never include uid fields such as card_uid, project_uid, project_column_uid, project_wiki_uid, bot_uid, thread_id, or session_id unless the user explicitly asks for an exact internal id.",
        "- When reporting an action result, use human-readable project, column, card, wiki, bot, or user names instead of uid values.",
        "- Never guess uid fields from human-readable names. If a user gives a card, column, wiki, project, bot, label, or user name, first use the relevant lookup/list API and then use the returned uid.",
        "- For card title tasks, use card lookup or project card list APIs before calling card detail, metadata, edit, relationship, checklist, comment, archive, or delete APIs.",
        "- For card creation or card movement tasks that name a board column, first call the project column list API and use the returned project_column_uid.",
        "- When a read/list API is needed to continue, call it immediately. Do not tell the user to wait for a lookup that you are not going to perform.",
    ]
)
_INTERNAL_UID_KEYS = (
    "card_uid",
    "project_uid",
    "project_column_uid",
    "project_wiki_uid",
    "bot_uid",
    "internal_bot_uid",
    "bot_log_uid",
    "chat_session_uid",
    "chat_history_uid",
    "scope_uid",
    "thread_id",
    "session_id",
)
_LANGBOARD_UID_PATTERN = re_compile(r"^[0-9A-Za-z]{11}$")


def _get_graph_config(tweaks: dict[str, Any]) -> tuple[str | None, dict[str, Any], str]:
    graph_config = tweaks.get("Graph")
    if isinstance(graph_config, dict):
        agent_llm = graph_config.get("agent_llm")
        settings = graph_config.get("settings")
        system_prompt = graph_config.get("system_prompt", "")
        return (
            agent_llm,
            settings if isinstance(settings, dict) else {},
            system_prompt if isinstance(system_prompt, str) else "",
        )

    if isinstance(tweaks.get("Ollama"), dict):
        return "Ollama", tweaks["Ollama"], _get_system_prompt(tweaks)
    if isinstance(tweaks.get("LM Studio"), dict):
        return "LM Studio", tweaks["LM Studio"], _get_system_prompt(tweaks)
    if isinstance(tweaks.get("Agent"), dict):
        settings = tweaks["Agent"]
        return settings.get("agent_llm"), settings, _get_system_prompt(tweaks)
    return None, {}, _get_system_prompt(tweaks)


def _get_system_prompt(tweaks: dict[str, Any]) -> str:
    prompt = tweaks.get("Prompt")
    if not isinstance(prompt, dict):
        return ""
    value = prompt.get("prompt", "")
    return value if isinstance(value, str) else ""


async def run_default_agent(state: DefaultGraphState) -> DefaultGraphState:
    input_value = state.get("input_value") or ""
    tweaks = state.get("tweaks") or {}
    _reset_run_transient_state(state)
    _set_runtime_context_state(state, tweaks)
    approval_request = _get_approval_request(tweaks, state)
    if approval_request is not None:
        state["approval_requests"] = (
            [approval_request] if isinstance(approval_request, dict) else [{"message": str(approval_request)}]
        )
        state["approval_result"] = interrupt(approval_request)
        approval_result = state["approval_result"]
        instruction = _get_approval_instruction(approval_result)
        if _is_rejected_approval_result(approval_result):
            state["response"] = _get_rejected_approval_response(state["approval_result"])
            return state
        if _is_approved_approval_result(approval_result):
            _apply_approved_api_context(tweaks, approval_result)
            if instruction:
                input_value = _create_instructed_input(input_value, instruction, allow_privileged_tools=True)
        elif instruction:
            _apply_instruction_api_context(tweaks)
            input_value = _create_instructed_input(input_value, instruction, allow_privileged_tools=False)

    agent_llm, settings, system_prompt = _get_graph_config(tweaks)
    chat_model = create_default_chat_model(agent_llm, settings)
    input_value = create_langboard_event_input(input_value, tweaks)

    if chat_model is None:
        raise RuntimeError("Default graph model is not configured.")

    messages: list[BaseMessage] = []
    if system_prompt:
        messages.append(SystemMessage(content=system_prompt))
    messages.append(SystemMessage(content=_LANGBOARD_RESPONSE_RULES))
    context_prompt = create_langboard_context_prompt(tweaks)
    if context_prompt:
        messages.append(SystemMessage(content=context_prompt))
    history_context_prompt = state.get("history_context_prompt")
    if history_context_prompt is None:
        history_context_prompt = create_langboard_history_context_prompt(tweaks, state)
    if history_context_prompt:
        messages.append(SystemMessage(content=history_context_prompt))
    messages.append(HumanMessage(content=input_value))

    tools, api_tool_context = await create_langboard_api_tool_context(tweaks)
    result, tool_results = await _invoke_agent(
        chat_model,
        messages,
        tools,
        tweaks=tweaks,
        state=state,
        api_tool_context=api_tool_context,
    )
    state["tool_results"] = tool_results
    content = result.content
    if isinstance(content, str):
        state["response"] = _sanitize_user_response(content)
    else:
        state["response"] = json_dumps(content, ensure_ascii=False)
    return state


def collect_default_history_context(state: DefaultGraphState) -> DefaultGraphState:
    tweaks = state.get("tweaks") or {}
    _set_runtime_context_state(state, tweaks)
    create_langboard_history_context_prompt(tweaks, state)
    return state


def _sanitize_user_response(content: str) -> str:
    sanitized = content
    for key in _INTERNAL_UID_KEYS:
        sanitized = re_sub(rf"\s*\({key}:\s*`?[^)`\s]+`?\)", "", sanitized)
        sanitized = re_sub(rf"(?im)^\s*{key}:\s*`?[^`\n]+`?\s*$\n?", "", sanitized)
    return sanitized.strip()


def _set_runtime_context_state(state: DefaultGraphState, tweaks: dict[str, Any]) -> None:
    state.update(create_runtime_context_state(tweaks))


def _reset_run_transient_state(state: DefaultGraphState) -> None:
    state["approval_requests"] = []
    state["approval_result"] = None
    state["tool_results"] = []
    state["response"] = ""


def _apply_approved_api_context(
    tweaks: dict[str, Any], approval_result: Any, *, apply_approval_policy: bool = True
) -> None:
    if not isinstance(approval_result, dict) or not approval_result.get("approved") or approval_result.get("rejected"):
        return

    variables = _get_variables(tweaks)
    app_api_token = approval_result.get("app_api_token")
    if isinstance(app_api_token, str) and app_api_token.strip():
        variables["app_api_token"] = app_api_token

    if not apply_approval_policy:
        return

    api_approval_policy = approval_result.get("api_approval_policy")
    if isinstance(api_approval_policy, dict):
        graph_config = tweaks.get("Graph")
        if isinstance(graph_config, dict):
            graph_config["api_approval_policy"] = api_approval_policy

        rest_data = _get_rest_data(variables)
        rest_data["api_approval_policy"] = api_approval_policy


def _apply_instruction_api_context(tweaks: dict[str, Any]) -> None:
    instruction_policy = {
        "read": "allow",
        "create": "deny",
        "edit": "deny",
        "delete": "deny",
    }
    graph_config = tweaks.get("Graph")
    if isinstance(graph_config, dict):
        graph_config["api_approval_policy"] = instruction_policy

    variables = _get_variables(tweaks)
    rest_data = _get_rest_data(variables)
    rest_data["api_approval_policy"] = instruction_policy


def _create_instructed_input(input_value: str, instruction: str, *, allow_privileged_tools: bool) -> str:
    tool_instruction = (
        "The requested privileged API action was approved. The human instruction below is the latest instruction and overrides the original request when they conflict. Do not execute the original requested action unless the latest instruction still asks for it. Use available API tools when needed."
        if allow_privileged_tools
        else "The requested privileged API action was not approved. Follow the instruction without using create, edit, or delete API tools."
    )
    return "\n\n".join(
        [
            "Latest human instruction after approval request:",
            instruction,
            "Original request for context only. Do not follow it when it conflicts with the latest human instruction:",
            input_value,
            tool_instruction,
        ]
    ).strip()


def _get_approval_request(tweaks: dict[str, Any], state: DefaultGraphState) -> dict[str, Any] | str | None:
    graph_config = tweaks.get("Graph")
    if not isinstance(graph_config, dict):
        return None

    approval_request = graph_config.get("approval_request")
    if approval_request is None:
        return None

    variables = _get_variables(tweaks)
    rest_data = _get_rest_data(variables)
    base_request = {
        "type": "approval_request",
        "thread_id": state.get("thread_id"),
        "session_id": state.get("session_id"),
        "origin_type": _get_origin_type(variables, rest_data),
        "scope_table": _get_scope_table(rest_data),
        "scope_uid": _get_scope_uid(rest_data, variables),
        "document_name": _get_document_name(rest_data),
    }

    if isinstance(approval_request, dict):
        return {
            **base_request,
            "preview": _get_preview(approval_request),
            "request_payload": _get_request_payload(approval_request),
            **approval_request,
        }

    if approval_request is True:
        return {
            **base_request,
            "message": "Approval required to continue this graph.",
            "preview": {"title": "Approval required", "summary": "Approval required to continue this graph."},
        }

    if isinstance(approval_request, str):
        return {
            **base_request,
            "message": approval_request,
            "preview": {"title": "Approval required", "summary": approval_request},
        }

    return None


def _get_variables(tweaks: dict[str, Any]) -> dict[str, Any]:
    variables = tweaks.get("LangboardCalledVariablesComponent")
    return variables if isinstance(variables, dict) else {}


def _get_rest_data(variables: dict[str, Any]) -> dict[str, Any]:
    rest_data = variables.get("rest_data")
    return rest_data if isinstance(rest_data, dict) else {}


def _get_origin_type(variables: dict[str, Any], rest_data: dict[str, Any]) -> str:
    origin_type = rest_data.get("origin_type")
    if isinstance(origin_type, str) and origin_type:
        return origin_type

    event = variables.get("event")
    if event == "chat":
        return "chat"
    if event == "bot_cron_scheduled":
        return "schedule"
    if event == "bot_mentioned":
        return "manual_scope_run"
    if event in {"trigger", "schedule", "editor", "manual_scope_run"}:
        return str(event)
    if isinstance(event, str) and event:
        return "trigger"
    return "chat"


def _get_scope_table(rest_data: dict[str, Any]) -> str:
    chat_scope = rest_data.get("chat_scope")
    if isinstance(chat_scope, str) and chat_scope in {"project", "project_column", "card", "project_wiki"}:
        return chat_scope
    if rest_data.get("card_uid"):
        return "card"
    if rest_data.get("project_wiki_uid"):
        return "project_wiki"
    if rest_data.get("project_column_uid"):
        return "project_column"
    return "project"


def _get_scope_uid(rest_data: dict[str, Any], variables: dict[str, Any] | None = None) -> str | None:
    for key in ("card_uid", "project_wiki_uid", "project_column_uid", "project_uid"):
        value = rest_data.get(key)
        if isinstance(value, str) and value:
            return value
    project_uid = (variables or {}).get("project_uid")
    if isinstance(project_uid, str) and project_uid:
        return project_uid
    return None


def _get_document_name(rest_data: dict[str, Any]) -> str | None:
    value = rest_data.get("document_name")
    if isinstance(value, str) and value:
        return value
    return None


def _get_preview(approval_request: dict[str, Any]) -> dict[str, Any]:
    preview = approval_request.get("preview")
    if isinstance(preview, dict):
        return preview

    message = approval_request.get("message")
    message = message if isinstance(message, str) and message else "Approval required to continue this graph."
    return {"title": "Approval required", "summary": message}


def _get_request_payload(approval_request: dict[str, Any]) -> dict[str, Any]:
    request_payload = approval_request.get("request_payload")
    return request_payload if isinstance(request_payload, dict) else {}


def _is_rejected_approval_result(approval_result: Any) -> bool:
    return (
        isinstance(approval_result, dict)
        and bool(approval_result.get("rejected"))
        and not approval_result.get("approved")
    )


def _is_approved_approval_result(approval_result: Any) -> bool:
    return (
        isinstance(approval_result, dict)
        and bool(approval_result.get("approved"))
        and not approval_result.get("rejected")
    )


def _get_approval_instruction(approval_result: Any) -> str:
    if not isinstance(approval_result, dict) or approval_result.get("rejected"):
        return ""

    instruction = approval_result.get("instruction")
    if isinstance(instruction, str) and instruction.strip():
        return instruction.strip()
    return ""


def _get_rejected_approval_response(approval_result: Any) -> str:
    if isinstance(approval_result, dict):
        reason = approval_result.get("reason")
        if isinstance(reason, str) and reason.strip():
            return f"Graph approval rejected: {reason.strip()}"
    return "Graph approval rejected."


async def _invoke_agent(
    chat_model: Any,
    messages: list[BaseMessage],
    tools: list[StructuredTool],
    *,
    tweaks: dict[str, Any] | None = None,
    state: DefaultGraphState | None = None,
    api_tool_context: dict[str, dict[str, Any]] | None = None,
) -> tuple[BaseMessage, list[dict[str, Any]]]:
    if not tools:
        return await _invoke_chat_model(chat_model, messages), []

    try:
        tool_enabled_model = chat_model.bind_tools(tools)
    except Exception:
        return await _invoke_chat_model(chat_model, messages), []

    tool_map = {tool.name: tool for tool in tools}
    current_messages = list(messages)
    tool_results: list[dict[str, Any]] = []
    result: BaseMessage | None = None

    for _ in range(3):
        result = await _invoke_chat_model(tool_enabled_model, current_messages)
        current_messages.append(result)

        tool_calls = getattr(result, "tool_calls", None) or []
        if not tool_calls:
            return result, tool_results

        for tool_call in tool_calls[:8]:
            tool_name = str(tool_call.get("name") or "")
            tool = tool_map.get(tool_name)
            if not tool:
                continue

            tool_args = tool_call.get("args") or {}
            approval_result = await _get_tool_approval_result(
                tool_name,
                tool_args if isinstance(tool_args, dict) else {},
                tweaks=tweaks,
                state=state,
                api_tool_context=api_tool_context,
            )
            if approval_result is not None:
                tool_results.append({"name": tool_name, "args": tool_args, "result": approval_result})
                current_messages.append(
                    ToolMessage(
                        content=str(approval_result),
                        tool_call_id=tool_call.get("id") or tool_name,
                    )
                )
                continue

            try:
                tool_result = await tool.ainvoke(tool_args)
            except Exception as exc:
                tool_result = f"Tool {tool_name} failed: {exc}"

            tool_results.append({"name": tool_name, "args": tool_args, "result": tool_result})
            current_messages.append(
                ToolMessage(
                    content=str(tool_result),
                    tool_call_id=tool_call.get("id") or tool_name,
                )
            )

    final_result = await _invoke_chat_model(chat_model, current_messages)
    return final_result, tool_results


async def _get_tool_approval_result(
    tool_name: str,
    tool_args: dict[str, Any],
    *,
    tweaks: dict[str, Any] | None,
    state: DefaultGraphState | None,
    api_tool_context: dict[str, dict[str, Any]] | None,
) -> str | None:
    if tweaks is None or state is None:
        return None

    tool_metadata = (api_tool_context or {}).get(tool_name)
    uid_resolution_result = await _resolve_tool_uid_args(tool_name, tool_args, tool_metadata)
    if uid_resolution_result:
        return uid_resolution_result

    invalid_uid_result = _get_invalid_uid_tool_arg_result(tool_name, tool_args)
    if invalid_uid_result:
        return invalid_uid_result

    approval_request = create_langboard_api_tool_approval_request(
        tweaks,
        tool_metadata,
        tool_args,
        tool_name=tool_name,
        thread_id=state.get("thread_id"),
        session_id=state.get("session_id"),
    )
    if approval_request is None:
        return None

    state["approval_requests"] = [approval_request]
    state["approval_result"] = interrupt(approval_request)
    approval_result = state["approval_result"]
    instruction = _get_approval_instruction(approval_result)

    if _is_rejected_approval_result(approval_result):
        return _get_rejected_approval_response(approval_result)

    if _is_approved_approval_result(approval_result):
        _apply_approved_api_context(tweaks, approval_result, apply_approval_policy=False)
        _apply_approved_tool_args(tool_args, tool_metadata)
        return None

    _apply_instruction_api_context(tweaks)
    if instruction:
        return f"Tool {tool_name} was not approved. Latest human instruction: {instruction}"
    return f"Tool {tool_name} was not approved."


def _apply_approved_tool_args(tool_args: dict[str, Any], tool_metadata: dict[str, Any] | None) -> None:
    if not isinstance(tool_metadata, dict) or tool_metadata.get("api_name") != "record_orchestration_bypass":
        return

    if isinstance(tool_args.get("form"), dict):
        tool_args["form"]["allowed"] = True
        return

    for key in ("form_allowed", "allowed"):
        if key in tool_args:
            tool_args[key] = True
            return

    tool_args["form_allowed"] = True


async def _resolve_tool_uid_args(
    tool_name: str, tool_args: dict[str, Any], tool_metadata: dict[str, Any] | None
) -> str:
    if not isinstance(tool_metadata, dict) or tool_metadata.get("api_name") != "create_card":
        return ""

    column_arg = _get_tool_arg(tool_args, "form_project_column_uid", "form", "project_column_uid")
    if not column_arg:
        return ""

    column_name = column_arg[1]
    if not isinstance(column_name, str) or _is_langboard_uid_like(column_name):
        return ""

    resolved_uid = await _resolve_project_column_uid(column_name, tool_args, tool_metadata)
    if not resolved_uid:
        return (
            f"Tool {tool_name} was not executed because project column {column_name!r} could not be resolved to an "
            "existing column uid. Use get_project_columns to inspect existing columns. Do not create a new column "
            "unless the user explicitly asks to create a column."
        )

    _set_tool_arg(tool_args, column_arg[0], "form", "project_column_uid", resolved_uid)
    return ""


async def _resolve_project_column_uid(
    column_name: str, tool_args: dict[str, Any], tool_metadata: dict[str, Any]
) -> str:
    base_url = tool_metadata.get("base_url")
    headers = tool_metadata.get("headers")
    variables = tool_metadata.get("variables")
    if not isinstance(base_url, str) or not isinstance(headers, dict) or not isinstance(variables, dict):
        return ""

    project_uid = _get_project_uid_for_tool(tool_args, variables)
    if not project_uid:
        return ""

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.get(
                f"{base_url}/board/{project_uid}/columns", headers=cast(dict[str, str], headers)
            )
            response.raise_for_status()
            data = response.json()
    except Exception:
        return ""

    columns = data.get("columns")
    if not isinstance(columns, list):
        return ""

    normalized_column_name = column_name.casefold()
    matches = [
        column
        for column in columns
        if isinstance(column, dict) and str(column.get("name") or "").casefold() == normalized_column_name
    ]
    if len(matches) != 1:
        return ""

    uid = matches[0].get("uid")
    return uid if isinstance(uid, str) and _is_langboard_uid_like(uid) else ""


def _get_project_uid_for_tool(tool_args: dict[str, Any], variables: dict[str, Any]) -> str:
    project_arg = _get_tool_arg(tool_args, "project_uid", "query", "project_uid")
    if project_arg and isinstance(project_arg[1], str):
        return project_arg[1]

    rest_data = _get_rest_data(variables)
    project_uid = rest_data.get("project_uid") or variables.get("project_uid")
    return project_uid if isinstance(project_uid, str) else ""


def _get_tool_arg(
    tool_args: dict[str, Any], direct_key: str, nested_key: str, nested_value_key: str
) -> tuple[str, Any] | None:
    if direct_key in tool_args:
        return direct_key, tool_args.get(direct_key)

    nested_value = tool_args.get(nested_key)
    if isinstance(nested_value, dict) and nested_value_key in nested_value:
        return f"{nested_key}.{nested_value_key}", nested_value.get(nested_value_key)

    return None


def _set_tool_arg(tool_args: dict[str, Any], path: str, nested_key: str, nested_value_key: str, value: str) -> None:
    if "." not in path:
        tool_args[path] = value
        return

    nested_value = tool_args.get(nested_key)
    if isinstance(nested_value, dict):
        nested_value[nested_value_key] = value


def _get_invalid_uid_tool_arg_result(tool_name: str, tool_args: dict[str, Any]) -> str:
    invalid_uid_args = _get_invalid_uid_arg_paths(tool_args)
    if not invalid_uid_args:
        return ""

    invalid_list = ", ".join(f"{path}={value!r}" for path, value in invalid_uid_args[:6])
    return (
        f"Tool {tool_name} was not executed because these UID arguments are not valid Langboard UIDs: "
        f"{invalid_list}. Use the relevant read/list API to resolve human-readable names to exact uid values, "
        f"then call {tool_name} again with those uid values. Never use names or placeholder values in uid fields."
    )


def _get_invalid_uid_arg_paths(value: Any, path: str = "", *, uid_context: bool = False) -> list[tuple[str, str]]:
    invalid_args: list[tuple[str, str]] = []
    if isinstance(value, dict):
        for key, child_value in value.items():
            child_path = f"{path}.{key}" if path else str(key)
            child_uid_context = _is_uid_arg_name(str(key))
            invalid_args.extend(_get_invalid_uid_arg_paths(child_value, child_path, uid_context=child_uid_context))
        return invalid_args

    if isinstance(value, (list, tuple)):
        for index, child_value in enumerate(value):
            child_path = f"{path}[{index}]"
            invalid_args.extend(_get_invalid_uid_arg_paths(child_value, child_path, uid_context=uid_context))
        return invalid_args

    if uid_context and isinstance(value, str) and value and not _is_langboard_uid_like(value):
        invalid_args.append((path, value))

    return invalid_args


def _is_uid_arg_name(name: str) -> bool:
    normalized_name = name.lower()
    return normalized_name in {"uid", "uids"} or normalized_name.endswith("_uid") or normalized_name.endswith("_uids")


def _is_langboard_uid_like(value: str) -> bool:
    return bool(_LANGBOARD_UID_PATTERN.fullmatch(value)) or (value.isdigit() and len(value) >= 15)


async def _invoke_chat_model(
    chat_model: BaseChatModel | _ConfigurableModel, messages: list[BaseMessage]
) -> BaseMessage:
    result = await asyncio.wait_for(chat_model.ainvoke(messages), timeout=Env.AI_REQUEST_TIMEOUT)
    if result is None:
        raise RuntimeError("Graph chat model returned no result.")
    return cast(BaseMessage, result)
