from enum import Enum
from ..core.routing.ApiPermission import ApiPermission
from ..core.routing.ApiSchemaHelper import ApiSchemaMap
from ..domain.models.ApiComfortTool import ApiComfortToolMap


def create_api_names_with_comfort_tools(
    api_names: list[str] | None,
    comfort_tool_names: list[str] | None,
    comfort_tools: dict[str, ApiComfortToolMap] | None = None,
) -> list[str]:
    api_tool_names: list[str] = []
    seen_api_names: set[str] = set()
    covered_api_names: set[str] = set()

    def add_api_name(api_name: str):
        if api_name in seen_api_names:
            return

        seen_api_names.add(api_name)
        api_tool_names.append(api_name)

    for comfort_tool_name in comfort_tool_names or []:
        comfort_tool = (comfort_tools or {}).get(comfort_tool_name)
        if not comfort_tool:
            continue

        covered_api_names.update(comfort_tool["api_names"])
        add_api_name(comfort_tool_name)

    for api_name in api_names or []:
        if api_name in covered_api_names:
            continue

        add_api_name(api_name)

    return api_tool_names


def expand_api_names_with_comfort_tools(
    api_names: list[str] | None,
    comfort_tool_names: list[str] | None,
    comfort_tools: dict[str, ApiComfortToolMap] | None = None,
) -> list[str]:
    comfort_tools = comfort_tools or {}
    expanded_api_names: list[str] = []
    seen_api_names: set[str] = set()

    def add_api_name(api_name: str):
        if api_name in seen_api_names:
            return

        seen_api_names.add(api_name)
        expanded_api_names.append(api_name)

    for comfort_tool_name in comfort_tool_names or []:
        comfort_tool = comfort_tools.get(comfort_tool_name)
        if not comfort_tool:
            continue

        for api_name in comfort_tool["api_names"]:
            add_api_name(api_name)

    for api_name in api_names or []:
        add_api_name(api_name)

    return expanded_api_names


def create_api_comfort_tool_schema(
    name: str, comfort_tool: ApiComfortToolMap, api_routes: dict[str, ApiSchemaMap]
) -> ApiSchemaMap:
    api_schemas = [api_routes[api_name] for api_name in comfort_tool["api_names"] if api_name in api_routes]
    path_params = list(dict.fromkeys(path_param for schema in api_schemas for path_param in schema["path_params"]))
    permission = _get_highest_api_permission([schema["permission"] for schema in api_schemas])
    request_schema_source = _create_api_comfort_tool_request_schema_source(path_params)
    return {
        "name": name,
        "path": f"/api/comfort/{name}",
        "path_params": [],
        "method": "POST",
        "permission": permission,
        "content_type": "application/json",
        "description": "\n".join(
            [
                comfort_tool["description"],
                "",
                "This comfort tool executes the registered base APIs and returns their combined responses.",
                "Use this tool when the user asks for the combined task. Do not answer from schema/status-code information alone.",
                f"Base APIs: {', '.join(comfort_tool['api_names'])}",
            ]
        ),
        "form": {
            "type": "object",
            "properties": {
                path_param: {"type": "string", "description": f"Shared parameter: {path_param}"}
                for path_param in path_params
            },
        },
        "query": None,
        "file_field": None,
        "request_schema_source": request_schema_source,
    }


def _get_highest_api_permission(permissions: list[str | ApiPermission]) -> str:
    permission_order = {
        ApiPermission.Read.value: 0,
        ApiPermission.Create.value: 1,
        ApiPermission.Edit.value: 2,
        ApiPermission.Delete.value: 3,
    }
    highest_permission = ApiPermission.Read.value
    highest_order = 0
    for permission in permissions:
        permission_value = permission.value if isinstance(permission, Enum) else permission
        permission_rank = permission_order.get(permission_value, 0)
        if permission_rank > highest_order:
            highest_order = permission_rank
            highest_permission = permission_value
    return highest_permission


def _create_api_comfort_tool_request_schema_source(path_params: list[str]) -> str:
    field_lines = [
        "    model_config = ConfigDict(extra='allow')",
        "    form_query: dict[str, Any] | None = Field(None, description='Optional query params to pass to base APIs.')",
        "    form_form: dict[str, Any] | None = Field(None, description='Optional JSON body fields to pass to base APIs.')",
    ]
    for path_param in path_params:
        field_lines.append(
            f"    form_{path_param}: str | None = Field(None, description='Shared parameter: {path_param}')"
        )

    return "\n".join(
        [
            "from typing import Any",
            "from pydantic import BaseModel, ConfigDict, Field",
            "",
            "class RequestForm(BaseModel):",
            *field_lines,
        ]
    )


def create_api_comfort_tool_prompt(
    comfort_tool_names: list[str] | None,
    comfort_tool_descriptions: dict[str, str] | None = None,
    comfort_tools: dict[str, ApiComfortToolMap] | None = None,
) -> str:
    comfort_tools = comfort_tools or {}
    prompt_lines: list[str] = []

    for comfort_tool_name in comfort_tool_names or []:
        comfort_tool = comfort_tools.get(comfort_tool_name)
        if not comfort_tool:
            continue

        lines = [
            f"- {comfort_tool['label']} ({comfort_tool_name})",
            f"  Base tools: {', '.join(comfort_tool['api_names'])}",
            f"  Default behavior: {comfort_tool['description']}",
        ]

        user_description = (comfort_tool_descriptions or {}).get(comfort_tool_name)
        if user_description:
            lines.append(f"  User description: {user_description}")

        prompt_lines.append("\n".join(lines))

    if not prompt_lines:
        return ""

    return "\n".join(
        [
            "Comfort tool instructions:",
            "The selected comfort tools are callable tools. When the task matches a comfort tool's behavior, call the comfort tool itself first instead of calling its base APIs one by one. The comfort tool executes its registered base APIs and returns the combined result. Only call base APIs separately when the comfort tool result is insufficient.",
            *prompt_lines,
        ]
    )
