from typing import Any, Mapping
from fastapi import Request, status
from langboard_shared.core.filter import AuthFilter
from langboard_shared.core.routing import AppRouter, JsonResponse
from langboard_shared.domain.models import Bot, User
from langboard_shared.domain.models.ApiComfortTool import ApiComfortToolMap
from langboard_shared.domain.services import DomainService
from langboard_shared.helpers.AgentApiPermissionHelper import get_agent_allowed_permissions
from langboard_shared.security import Auth
from pydantic import BaseModel, ConfigDict, Field
from starlette.datastructures import Headers
from .BatchForm import BatchFormRequestSchema
from .BatchRunner import create_batch_response, execute_batch_request_schemas


class ApiComfortToolRunForm(BaseModel):
    model_config = ConfigDict(extra="allow")

    query: dict[str, Any] | None = Field(default=None)
    form: dict[str, Any] | None = Field(default=None)


@AppRouter.api.post(
    "/api/comfort/{comfort_tool_name}",
    tags=["API comfort tools"],
    description="Run an API comfort tool. The comfort tool executes its registered base APIs and returns their combined responses.",
)
@AuthFilter.add()
async def run_api_comfort_tool(
    request: Request,
    comfort_tool_name: str,
    form: ApiComfortToolRunForm,
    user_or_bot: User | Bot = Auth.scope("all"),
    service: DomainService = DomainService.scope(),
):
    comfort_tool = service.app_setting.get_api_comfort_tool_list().get(comfort_tool_name)
    if not comfort_tool:
        return JsonResponse(content={"message": "API comfort tool not found."}, status_code=status.HTTP_404_NOT_FOUND)

    allowed_permissions = get_agent_allowed_permissions(Headers(raw=request.headers.raw), default_read=True)
    shared_params = _create_comfort_tool_shared_params(form)
    request_schemas: list[BatchFormRequestSchema] = []
    runnable_api_names: list[str] = []
    skipped_responses: dict[str, dict] = {}
    for api_name in comfort_tool["api_names"]:
        request_schema = _create_comfort_tool_request_schema(api_name, shared_params, comfort_tool)
        missing_params = _get_missing_required_params(api_name, request_schema)
        if missing_params:
            skipped_responses[api_name] = create_batch_response(
                {
                    "skipped": True,
                    "message": f"Skipped because required parameter(s) are missing: {', '.join(missing_params)}",
                }
            )
            continue

        request_schemas.append(request_schema)
        runnable_api_names.append(api_name)

    responses = await execute_batch_request_schemas(request, request_schemas, user_or_bot, allowed_permissions)
    response_by_api = {
        **skipped_responses,
        **{api_name: response for api_name, response in zip(runnable_api_names, responses)},
    }
    return JsonResponse(
        content={
            "comfort_tool": comfort_tool_name,
            "base_apis": comfort_tool["api_names"],
            "responses": {api_name: response_by_api[api_name] for api_name in comfort_tool["api_names"]},
        }
    )


def _create_comfort_tool_shared_params(form: ApiComfortToolRunForm) -> dict[str, Any]:
    data = form.model_dump(exclude_none=True)
    extra = form.model_extra or {}
    query = data.pop("query", {}) or {}
    body_form = data.pop("form", {}) or {}
    return {**query, **body_form, **data, **extra}


def _create_comfort_tool_request_schema(
    api_name: str, shared_params: dict[str, Any], comfort_tool: ApiComfortToolMap
) -> BatchFormRequestSchema:
    api_schema = AppRouter.api_routes.get(api_name)
    method = (api_schema or {}).get("method", "GET")
    api_queries = _get_dict_value(comfort_tool, "api_queries")
    api_forms = _get_dict_value(comfort_tool, "api_forms")
    default_query = _get_dict_value(comfort_tool, "query")
    default_form = _get_dict_value(comfort_tool, "form")
    api_query = _get_dict_value(api_queries, api_name)
    api_form = _get_dict_value(api_forms, api_name)

    query = {**default_query, **api_query, **shared_params}
    body_form = None if method.upper() == "GET" else {**default_form, **api_form, **shared_params}
    return BatchFormRequestSchema(
        path_or_api_name=api_name,
        method=method,
        query=query,
        form=body_form,
    )


def _get_missing_required_params(api_name: str, request_schema: BatchFormRequestSchema) -> list[str]:
    api_schema = AppRouter.api_routes.get(api_name)
    if not api_schema:
        return []

    request_params = {**(request_schema.query or {}), **(request_schema.form or {})}
    required_params = [
        *api_schema["path_params"],
        *_get_required_schema_fields(api_schema.get("query")),
        *_get_required_schema_fields(api_schema.get("form")),
    ]
    return [param for param in required_params if request_params.get(param) is None]


def _get_required_schema_fields(schema: dict[str, Any] | None) -> list[str]:
    required = (schema or {}).get("required")
    return [str(field) for field in required] if isinstance(required, list) else []


def _get_dict_value(source: Mapping[str, Any], key: str) -> dict[str, Any]:
    value = source.get(key)
    return value if isinstance(value, dict) else {}
