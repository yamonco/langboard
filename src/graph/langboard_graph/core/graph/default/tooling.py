from json import dumps as json_dumps
from json import loads as json_loads
from re import sub as re_sub
from typing import Any, Literal
from urllib.parse import urlparse
import httpx
from langboard_shared.core.security import AuthSecurity
from langboard_shared.Env import Env
from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field, create_model


_GRAPH_COMPONENT = "Graph"
_API_TOOLS_COMPONENT = "LangboardCalledAPIToolsComponent"
_VARIABLES_COMPONENT = "LangboardCalledVariablesComponent"
_LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "0.0.0.0", "::1"}
_API_APPROVAL_POLICIES = {"allow", "ask", "deny"}
_MAX_CARD_DESCRIPTION_PROMPT_LENGTH = 1200
_DEFAULT_API_APPROVAL_POLICY = {
    "read": "allow",
    "create": "ask",
    "edit": "ask",
    "delete": "ask",
}


def create_langboard_context_prompt(tweaks: dict[str, Any]) -> str:
    variables = _get_variables(tweaks)
    if not variables:
        return ""

    rest_data = _get_rest_data(variables)
    lines = [
        "Langboard runtime context:",
        f"- event: {variables.get('event') or 'chat'}",
        f"- project_uid: {variables.get('project_uid') or 'none'}",
        f"- current_runner_type: {variables.get('current_runner_type') or 'unknown'}",
    ]

    current_runner_data = variables.get("current_runner_data")
    if current_runner_data:
        lines.append(f"- current_runner_data: {json_dumps(current_runner_data, ensure_ascii=False)}")
    if rest_data:
        lines.append(f"- rest_data: {json_dumps(rest_data, ensure_ascii=False)}")

    return "\n".join(lines)


async def create_langboard_entity_context_prompt(tweaks: dict[str, Any], input_value: str) -> str:
    if "card" not in input_value.lower() and "카드" not in input_value:
        return ""

    variables = _get_variables(tweaks)
    project_uid = variables.get("project_uid")
    app_api_token = variables.get("app_api_token")
    if not isinstance(project_uid, str) or not project_uid or not isinstance(app_api_token, str) or not app_api_token:
        return ""

    cards = await _fetch_project_cards(tweaks, variables, project_uid, app_api_token)
    matched_cards = _filter_mentioned_cards(cards, input_value)
    if not matched_cards:
        return ""

    lines = [
        "Langboard current project card matches:",
        "- Use these uid values internally for tool arguments, but do not expose them in normal user-facing answers.",
    ]
    for card in matched_cards[:20]:
        title = card.get("title")
        uid = card.get("uid")
        column_name = card.get("project_column_name")
        if isinstance(title, str) and isinstance(uid, str):
            column_part = f", column={column_name}" if isinstance(column_name, str) and column_name else ""
            description = _get_card_description_prompt(card.get("description"))
            lines.append(
                f"- title={title}, uid={uid}{column_part}, description={json_dumps(description, ensure_ascii=False)}"
            )

    return "\n".join(lines)


def create_langboard_event_input(input_value: str, tweaks: dict[str, Any]) -> str:
    if input_value.strip():
        return input_value

    variables = _get_variables(tweaks)
    if not variables:
        return "Handle the Langboard graph request."

    event = variables.get("event") or "chat"
    rest_data = _get_rest_data(variables)
    return "\n".join(
        [
            f"Handle the Langboard event: {event}.",
            "Use the runtime context and available tools to decide the next action.",
            f"Event data: {json_dumps(rest_data, ensure_ascii=False)}" if rest_data else "Event data: {}",
        ]
    )


async def _fetch_project_cards(
    tweaks: dict[str, Any], variables: dict[str, Any], project_uid: str, app_api_token: str
) -> list[dict[str, Any]]:
    base_url = _get_base_url(tweaks, variables)
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.get(f"{base_url}/board/{project_uid}/cards", headers=_get_headers(app_api_token))
            response.raise_for_status()
            data = response.json()
    except Exception:
        return []

    cards = data.get("cards")
    return [card for card in cards if isinstance(card, dict)] if isinstance(cards, list) else []


def _filter_mentioned_cards(cards: list[dict[str, Any]], input_value: str) -> list[dict[str, Any]]:
    normalized_input = input_value.casefold()
    matched_cards: list[dict[str, Any]] = []
    for card in cards:
        title = card.get("title")
        if not isinstance(title, str) or not title:
            continue
        normalized_title = title.casefold()
        if normalized_title in normalized_input or normalized_input in normalized_title:
            matched_cards.append(card)

    return matched_cards


def _get_card_description_prompt(value: Any) -> str:
    content = _get_editor_content(value)
    if len(content) <= _MAX_CARD_DESCRIPTION_PROMPT_LENGTH:
        return content
    return f"{content[:_MAX_CARD_DESCRIPTION_PROMPT_LENGTH]}..."


def _get_editor_content(value: Any) -> str:
    if isinstance(value, BaseModel):
        value = value.model_dump()

    if isinstance(value, dict):
        content = value.get("content")
        return content if isinstance(content, str) else ""

    if isinstance(value, str):
        stripped_value = value.strip()
        if not stripped_value:
            return ""
        if stripped_value.startswith("{"):
            try:
                return _get_editor_content(json_loads(stripped_value))
            except ValueError:
                return stripped_value
        return stripped_value

    return ""


async def create_langboard_api_tools(tweaks: dict[str, Any]) -> list[StructuredTool]:
    tools, _ = await create_langboard_api_tool_context(tweaks)
    return tools


async def create_langboard_api_tool_context(
    tweaks: dict[str, Any],
) -> tuple[list[StructuredTool], dict[str, dict[str, Any]]]:
    variables = _get_variables(tweaks)
    api_names = _get_api_names(tweaks)
    app_api_token = variables.get("app_api_token")
    if not api_names or not isinstance(app_api_token, str) or not app_api_token.strip():
        return [], {}

    base_url = _get_base_url(tweaks, variables)
    headers = _get_headers(app_api_token)
    schemas = await _fetch_api_schemas(base_url, api_names, headers)
    approval_policy = _get_api_approval_policy(tweaks, variables)

    tools: list[StructuredTool] = []
    tool_context: dict[str, dict[str, Any]] = {}
    for api_name in api_names:
        schema = schemas.get(api_name)
        if not isinstance(schema, dict):
            continue
        if _get_schema_policy_decision(schema, approval_policy) == "deny":
            continue
        tool = _create_api_tool(api_name, schema, base_url, headers, variables)
        tools.append(tool)
        tool_context[tool.name] = {
            "api_name": api_name,
            "schema": schema,
            "base_url": base_url,
            "headers": headers,
            "variables": variables,
        }

    return tools, tool_context


def create_langboard_api_tool_approval_request(
    tweaks: dict[str, Any],
    tool_metadata: dict[str, Any] | None,
    tool_args: dict[str, Any],
    *,
    tool_name: str,
    thread_id: str | None,
    session_id: str | None,
) -> dict[str, Any] | None:
    if not tool_metadata:
        return None

    schema = tool_metadata.get("schema")
    api_name = tool_metadata.get("api_name")
    if not isinstance(schema, dict) or not isinstance(api_name, str) or not api_name:
        return None

    variables = _get_variables(tweaks)
    approval_policy = _get_api_approval_policy(tweaks, variables)
    permission = _get_schema_permission(schema)
    if _get_schema_policy_decision(schema, approval_policy) != "ask":
        return None

    rest_data = _get_rest_data(variables)
    message = f"Approval required before this graph calls {api_name}."
    return {
        "type": "approval_request",
        "thread_id": thread_id,
        "session_id": session_id,
        "origin_type": _get_origin_type(variables, rest_data),
        "scope_table": _get_scope_table(rest_data),
        "scope_uid": _get_scope_uid(rest_data, variables),
        "document_name": _get_document_name(rest_data),
        "action_type": "api_call",
        "permission": permission,
        "tool_name": tool_name,
        "api_name": api_name,
        "message": message,
        "preview": {
            "title": "API approval required",
            "summary": message,
            "details": f"{permission}: {api_name}",
        },
        "request_payload": {
            "api_name": api_name,
            "api_names": [api_name],
            "permissions": [permission],
            "policy": approval_policy,
            "rest_data": rest_data,
            "tool_args": tool_args,
        },
    }


def _get_variables(tweaks: dict[str, Any]) -> dict[str, Any]:
    variables = tweaks.get(_VARIABLES_COMPONENT)
    return variables if isinstance(variables, dict) else {}


def _get_api_approval_policy(tweaks: dict[str, Any], variables: dict[str, Any]) -> dict[str, str]:
    graph_config = tweaks.get(_GRAPH_COMPONENT)
    policy = graph_config.get("api_approval_policy") if isinstance(graph_config, dict) else None
    if not isinstance(policy, dict):
        policy = _get_rest_data(variables).get("api_approval_policy")
    if not isinstance(policy, dict):
        policy = _DEFAULT_API_APPROVAL_POLICY

    normalized_policy: dict[str, str] = {}
    for permission, decision in policy.items():
        permission_name = str(permission)
        decision_name = str(decision)
        if decision_name not in _API_APPROVAL_POLICIES:
            continue
        normalized_policy[permission_name] = decision_name

    return {**_DEFAULT_API_APPROVAL_POLICY, **normalized_policy}


def _get_schema_policy_decision(schema: dict[str, Any], approval_policy: dict[str, str]) -> str:
    return approval_policy.get(_get_schema_permission(schema), "allow")


def _get_schema_permission(schema: dict[str, Any]) -> str:
    permission = schema.get("permission")
    permission_value = getattr(permission, "value", permission)
    return str(permission_value or "read")


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


def _get_api_names(tweaks: dict[str, Any]) -> list[str]:
    graph = tweaks.get(_GRAPH_COMPONENT)
    if isinstance(graph, dict) and isinstance(graph.get("api_names"), list):
        return [str(api_name) for api_name in graph["api_names"] if api_name]

    tools = tweaks.get(_API_TOOLS_COMPONENT)
    if isinstance(tools, dict) and isinstance(tools.get("api_names"), list):
        return [str(api_name) for api_name in tools["api_names"] if api_name]

    variables = _get_variables(tweaks)
    api_names = variables.get("api_names")
    return [str(api_name) for api_name in api_names if api_name] if isinstance(api_names, list) else []


def _get_base_url(tweaks: dict[str, Any], variables: dict[str, Any]) -> str:
    api_tools = tweaks.get(_API_TOOLS_COMPONENT)
    base_url = None
    if isinstance(api_tools, dict):
        base_url = api_tools.get("base_url")
    base_url = base_url or variables.get("base_url") or Env.API_URL
    return _resolve_graph_api_url(str(base_url).rstrip("/"))


def _resolve_graph_api_url(base_url: str) -> str:
    parsed_base_url = urlparse(base_url)
    if parsed_base_url.hostname not in _LOOPBACK_HOSTS:
        return base_url

    internal_url = Env.API_INTERNAL_URL
    parsed_internal_url = urlparse(internal_url)
    if parsed_internal_url.hostname and parsed_internal_url.hostname not in _LOOPBACK_HOSTS:
        return internal_url

    return base_url


def _get_headers(app_api_token: str) -> dict[str, str]:
    return {
        "Accept": "application/json",
        "Content-Type": "application/json",
        AuthSecurity.API_TOKEN_HEADER: app_api_token,
    }


async def _fetch_api_schemas(base_url: str, api_names: list[str], headers: dict[str, str]) -> dict[str, dict[str, Any]]:
    async with httpx.AsyncClient(timeout=10) as client:
        response = await client.get(
            f"{base_url}/schema/api/list",
            params={"api_names": ",".join(api_names)},
            headers=headers,
        )
        response.raise_for_status()
        data = response.json()
    schemas = data.get("schemas")
    return schemas if isinstance(schemas, dict) else {}


def _create_api_tool(
    api_name: str, schema: dict[str, Any], base_url: str, headers: dict[str, str], variables: dict[str, Any]
) -> StructuredTool:
    field_sources: dict[str, tuple[Literal["path", "query", "form"], str]] = {}
    args_schema = _create_args_schema(api_name, schema, variables, field_sources)
    tool_name = _safe_tool_name(api_name)

    async def call_api(**kwargs: Any) -> str:
        return await _call_api_tool(api_name, schema, base_url, headers, variables, field_sources, kwargs)

    return StructuredTool.from_function(
        coroutine=call_api,
        name=tool_name,
        description=schema.get("description") or f"Call Langboard API: {api_name}",
        args_schema=args_schema,
    )


def _create_args_schema(
    api_name: str,
    schema: dict[str, Any],
    variables: dict[str, Any],
    field_sources: dict[str, tuple[Literal["path", "query", "form"], str]],
) -> type[BaseModel]:
    fields: dict[str, Any] = {}
    rest_data = _get_rest_data(variables)
    project_uid = variables.get("project_uid")

    for path_param in schema.get("path_params") or []:
        default = rest_data.get(path_param, project_uid if path_param == "project_uid" else None)
        field_name = _safe_field_name(str(path_param), fields)
        field_sources[field_name] = ("path", str(path_param))
        fields[field_name] = _create_model_field(
            default=default,
            required=default is None,
            description=f"Path parameter: {path_param}",
            source_name=str(path_param),
        )

    _add_schema_part_fields(fields, field_sources, "query", schema.get("query"), rest_data)
    _add_schema_part_fields(fields, field_sources, "form", schema.get("form"), rest_data)

    if "query" not in fields:
        fields["query"] = (dict[str, Any] | None, Field(None, description="Additional query parameters."))
    if "form" not in fields:
        fields["form"] = (dict[str, Any] | None, Field(None, description="Additional JSON body fields."))

    return create_model(f"{_safe_model_name(api_name)}Request", **fields)


def _add_schema_part_fields(
    fields: dict[str, Any],
    field_sources: dict[str, tuple[Literal["path", "query", "form"], str]],
    source_type: Literal["query", "form"],
    schema_part: Any,
    rest_data: dict[str, Any],
) -> None:
    if not isinstance(schema_part, dict):
        return
    properties = schema_part.get("properties")
    if not isinstance(properties, dict):
        return
    required_fields = set(schema_part.get("required") or [])

    for source_name, field_schema in properties.items():
        if not isinstance(field_schema, dict):
            field_schema = {}
        field_name = _safe_field_name(f"{source_type}_{source_name}", fields)
        field_sources[field_name] = (source_type, str(source_name))
        default = rest_data.get(source_name)
        fields[field_name] = _create_model_field(
            default=default,
            required=source_name in required_fields and default is None,
            description=field_schema.get("description") or field_schema.get("title") or f"{source_type}: {source_name}",
            schema_type=field_schema.get("type"),
            source_name=str(source_name),
        )


def _create_model_field(
    *, default: Any, required: bool, description: str, schema_type: str | None = None, source_name: str | None = None
) -> tuple[Any, Any]:
    py_type = _get_python_type(schema_type)
    if source_name and _is_uid_source_name(source_name):
        description = (
            f"{description}. Use the exact 11-character uid returned by a read/list API. "
            "Never use a display name, guessed uid, or placeholder."
        )
    if required:
        return py_type, Field(..., description=description)
    return py_type | None, Field(default, description=description)


def _is_uid_source_name(source_name: str) -> bool:
    normalized_name = source_name.lower()
    return normalized_name in {"uid", "uids"} or normalized_name.endswith("_uid") or normalized_name.endswith("_uids")


def _get_python_type(schema_type: str | None) -> type:
    return {
        "string": str,
        "integer": int,
        "number": float,
        "boolean": bool,
        "array": list,
        "object": dict,
    }.get(schema_type or "", Any)


async def _call_api_tool(
    api_name: str,
    schema: dict[str, Any],
    base_url: str,
    headers: dict[str, str],
    variables: dict[str, Any],
    field_sources: dict[str, tuple[Literal["path", "query", "form"], str]],
    kwargs: dict[str, Any],
) -> str:
    query, form = _split_tool_args(kwargs, field_sources)
    _normalize_editor_content_form(schema, form)
    project_uid = variables.get("project_uid")
    if project_uid:
        query.setdefault("project_uid", project_uid)

    rest_data = _get_rest_data(variables)
    for path_param in schema.get("path_params") or []:
        if path_param not in query and path_param in rest_data:
            query[path_param] = rest_data[path_param]

    async with httpx.AsyncClient(timeout=30) as client:
        if str(schema.get("path", "")).startswith("/api/comfort/"):
            response = await client.post(
                f"{base_url}/api/comfort/{api_name}",
                headers=headers,
                json={"query": query or None, "form": form or None},
            )
        else:
            request_schema = {
                "path_or_api_name": api_name,
                "method": str(schema.get("method") or "GET"),
                "query": query or None,
                "form": form or None,
            }
            response = await client.post(
                f"{base_url}/batch",
                headers=headers,
                json={"request_schemas": [request_schema]},
            )

    content_type = response.headers.get("content-type", "")
    if "application/json" in content_type:
        return json_dumps(response.json(), ensure_ascii=False)
    return response.text


def _split_tool_args(
    kwargs: dict[str, Any], field_sources: dict[str, tuple[Literal["path", "query", "form"], str]]
) -> tuple[dict[str, Any], dict[str, Any]]:
    query = kwargs.pop("query", None) or {}
    form = kwargs.pop("form", None) or {}
    query = query if isinstance(query, dict) else {}
    form = form if isinstance(form, dict) else {}

    for field_name, value in kwargs.items():
        if value is None:
            continue
        source = field_sources.get(field_name)
        if source is None:
            query[field_name] = value
            continue

        source_type, source_name = source
        if source_type in {"path", "query"}:
            query[source_name] = value
        else:
            form[source_name] = value

    return query, form


def _normalize_editor_content_form(schema: dict[str, Any], form: dict[str, Any]) -> None:
    form_schema = schema.get("form")
    properties = form_schema.get("properties") if isinstance(form_schema, dict) else None
    if not isinstance(properties, dict):
        return

    for field_name in ("description", "content"):
        value = form.get(field_name)
        field_schema = properties.get(field_name)
        if isinstance(value, str) and _is_editor_content_schema(field_schema):
            form[field_name] = {"content": value}


def _is_editor_content_schema(field_schema: Any) -> bool:
    if not isinstance(field_schema, dict):
        return False

    any_of = field_schema.get("anyOf")
    if isinstance(any_of, list):
        return any(_is_editor_content_schema(option) for option in any_of)

    ref = field_schema.get("$ref")
    if isinstance(ref, str) and ref.endswith("/EditorContentModel"):
        return True

    if field_schema.get("type") != "object":
        return False

    properties = field_schema.get("properties")
    if not isinstance(properties, dict):
        return True
    return "content" in properties


def _safe_tool_name(name: str) -> str:
    safe_name = re_sub(r"[^a-zA-Z0-9_]", "_", name).strip("_")
    return safe_name or "langboard_api_tool"


def _safe_model_name(name: str) -> str:
    safe_name = re_sub(r"[^a-zA-Z0-9_]", "_", name).strip("_")
    if not safe_name:
        return "LangboardApiTool"
    return "".join(part.capitalize() for part in safe_name.split("_") if part) or "LangboardApiTool"


def _safe_field_name(name: str, existing: dict[str, Any]) -> str:
    safe_name = re_sub(r"[^a-zA-Z0-9_]", "_", name).strip("_")
    if not safe_name or safe_name[0].isdigit():
        safe_name = f"field_{safe_name}"
    original = safe_name
    index = 2
    while safe_name in existing:
        safe_name = f"{original}_{index}"
        index += 1
    return safe_name
