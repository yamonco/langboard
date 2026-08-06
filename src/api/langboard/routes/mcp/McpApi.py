import inspect
from typing import Any
from fastapi import Request
from langboard_shared.core.filter import AuthFilter
from langboard_shared.core.routing import ApiErrorCode, ApiException, ApiPermission, AppRouter, JsonResponse
from langboard_shared.core.security import AuthSecurity
from langboard_shared.domain.models import McpRole, User
from langboard_shared.domain.models.McpRole import McpRoleAction
from langboard_shared.domain.services import DomainService
from langboard_shared.filter import RoleFilter
from langboard_shared.infrastructure.repositories import Repository
from langboard_shared.security import RoleFinder
from pydantic import BaseModel
from ...mcp_integration import McpTool
from ...mcp_tools.RoleChecker import McpRoleChecker


@AppRouter.schema(permission=ApiPermission.Read)
@AppRouter.api.get("/mcp/tools", tags=["MCP"], description="List all available MCP tools", response_model=None)
@RoleFilter.add(McpRole, [McpRoleAction.Read], RoleFinder.mcp)
@AuthFilter.add("user")
def get_mcp_tools():
    tools = McpTool.get_tools()
    return JsonResponse(
        content={
            "tools": [
                {"name": name, "description": data["description"], "input_schema": data["input_schema"]}
                for name, data in tools.items()
            ]
        }
    )


@AppRouter.schema(permission=ApiPermission.Delete)
@AppRouter.api.post("/mcp/tools/{tool_name}", tags=["MCP"], description="Execute an MCP tool", response_model=None)
@RoleFilter.add(McpRole, [McpRoleAction.Read], RoleFinder.mcp)
@AuthFilter.add("user")
async def execute_mcp_tool(tool_name: str, request: Request):
    tool = McpTool.get_tool(tool_name)
    if not tool:
        raise ApiException.NotFound_404(ApiErrorCode.NF1004)

    user_or_bot = request.scope.get("auth")
    if not user_or_bot:
        raise ApiException.Unauthorized_401(ApiErrorCode.AU1001)
    if not isinstance(user_or_bot, User):
        raise ApiException.Forbidden_403(ApiErrorCode.PE1001)

    # Extract and validate MCP tool group UID from header only
    mcp_tool_group_uid = request.headers.get(AuthSecurity.MCP_TOOL_GROUP_UID_HEADER)

    if not mcp_tool_group_uid:
        raise ApiException.BadRequest_400(ApiErrorCode.VA0000)

    # Get MCP tool group and validate access
    repo = Repository()
    service = DomainService()
    service.initialize(repo)
    try:
        tool_group = service.mcp_tool_group.get_by_id_like(mcp_tool_group_uid)
        if not tool_group:
            raise ApiException.NotFound_404(ApiErrorCode.NF3006)

        if tool_group.activated_at is None:
            raise ApiException.Forbidden_403(ApiErrorCode.PE1001)

        if tool_name not in tool_group.tools:
            raise ApiException.Forbidden_403(ApiErrorCode.PE1001)

        if tool.get("accessible_type", "all") not in ("all", "user"):
            raise ApiException.Forbidden_403(ApiErrorCode.PE1001)

        # Check if it's a personal tool group and validate ownership
        if tool_group.user_id is not None:
            api_key = request.scope.get("api_key")
            if not api_key:
                raise ApiException.Forbidden_403(ApiErrorCode.PE1001)

            # Validate that the API key belongs to the same user as the tool group
            if api_key.user_id != tool_group.user_id:
                raise ApiException.Forbidden_403(ApiErrorCode.PE1001)

        try:
            arguments = await request.json()
        except ValueError as exc:
            raise ApiException.BadRequest_400(ApiErrorCode.VA0000) from exc
        if not isinstance(arguments, dict):
            raise ApiException.BadRequest_400(ApiErrorCode.VA0000)

        handler = tool["handler"]
        sig = inspect.signature(handler)
        role_checker = McpRoleChecker(service)

        if not role_checker.check_permission(handler, user_or_bot, arguments):
            raise ApiException.Forbidden_403(ApiErrorCode.PE1001)

        if "user_or_bot" in sig.parameters:
            arguments["user_or_bot"] = user_or_bot
        elif "user" in sig.parameters:
            authenticated_user = user_or_bot if isinstance(user_or_bot, User) else None
            if not authenticated_user:
                raise ApiException.Forbidden_403(ApiErrorCode.PE1001)
            arguments["user"] = authenticated_user

        for param_name, param in sig.parameters.items():
            if param_name == "service" and param.annotation == DomainService:
                arguments["service"] = service
                break

        result = await handler(**arguments) if inspect.iscoroutinefunction(handler) else handler(**arguments)
        return JsonResponse(content={"result": serialize_mcp_result(result)})
    finally:
        service.close()
        repo.close()


def serialize_mcp_result(value: Any) -> Any:
    """Recursively convert typed MCP results to JSON-native values."""

    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    if isinstance(value, dict):
        return {key: serialize_mcp_result(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [serialize_mcp_result(item) for item in value]
    return value
