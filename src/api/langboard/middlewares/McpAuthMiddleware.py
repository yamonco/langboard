from contextvars import ContextVar
from typing import Any
from fastapi import status
from langboard_shared.core.routing import ApiErrorCode, BaseMiddleware, JsonResponse
from langboard_shared.core.security import AuthSecurity
from langboard_shared.domain.models import ApiKeySetting, User
from langboard_shared.domain.models.McpRole import McpRoleAction
from langboard_shared.domain.services import DomainService
from langboard_shared.Env import Env
from langboard_shared.helpers import MiddlewareHelper
from starlette.datastructures import Headers


mcp_auth_context: ContextVar[Any] = ContextVar("mcp_auth_context", default=None)


class McpAuthMiddleware(BaseMiddleware):
    """Authentication middleware for MCP SSE app."""

    __auto_load__ = False

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        is_secure = Env.PUBLIC_UI_URL.startswith("https://")

        validation_result = MiddlewareHelper.validate_auth(scope)
        if isinstance(validation_result, int):
            response = JsonResponse(status_code=validation_result)
            if validation_result != status.HTTP_422_UNPROCESSABLE_CONTENT:
                response.delete_cookie(
                    Env.REFRESH_TOKEN_NAME,
                    domain=Env.DOMAIN if Env.DOMAIN else None,
                    httponly=True,
                    secure=is_secure,
                )
            await response(scope, receive, send)
            return

        # Extract and validate mcp_tool_group_uid from header only
        headers = Headers(scope=scope)
        mcp_tool_group_uid = headers.get(
            AuthSecurity.MCP_TOOL_GROUP_UID_HEADER, headers.get(AuthSecurity.MCP_TOOL_GROUP_UID_HEADER.lower())
        )

        if not mcp_tool_group_uid:
            response = JsonResponse(
                content={"error": "X-MCP-Tool-Group-UID header is required"},
                status_code=status.HTTP_400_BAD_REQUEST,
            )
            await response(scope, receive, send)
            return

        # Validate MCP tool group and user ownership
        api_key: ApiKeySetting | None = scope.get("api_key")
        service = DomainService()
        try:
            await self._validate_and_dispatch(
                scope,
                receive,
                send,
                validation_result,
                api_key,
                mcp_tool_group_uid,
                service,
            )
        finally:
            service.close()

    async def _validate_and_dispatch(
        self,
        scope,
        receive,
        send,
        validation_result,
        api_key: ApiKeySetting | None,
        mcp_tool_group_uid: str,
        service: DomainService,
    ) -> None:
        tool_group = service.mcp_tool_group.get_by_id_like(mcp_tool_group_uid)
        if not tool_group:
            response = JsonResponse(ApiErrorCode.NF3006, status_code=status.HTTP_404_NOT_FOUND)
            await response(scope, receive, send)
            return

        if tool_group.activated_at is None:
            response = JsonResponse(ApiErrorCode.PE1001, status_code=status.HTTP_403_FORBIDDEN)
            await response(scope, receive, send)
            return

        # Check if it's a personal tool group and validate ownership
        if tool_group.user_id is not None:
            if not api_key:
                response = JsonResponse(ApiErrorCode.PE1001, status_code=status.HTTP_403_FORBIDDEN)
                await response(scope, receive, send)
                return

            # Validate that the API key belongs to the same user as the tool group
            if api_key.user_id != tool_group.user_id:
                response = JsonResponse(ApiErrorCode.PE1001, status_code=status.HTTP_403_FORBIDDEN)
                await response(scope, receive, send)
                return

        if isinstance(validation_result, User) and not validation_result.is_admin:
            mcp_role = service.mcp_tool_group.get_role(validation_result)
            if not mcp_role or not mcp_role.is_granted(McpRoleAction.Read):
                response = JsonResponse(ApiErrorCode.PE1001, status_code=status.HTTP_403_FORBIDDEN)
                await response(scope, receive, send)
                return

        # Store auth data and validated tool group in context
        auth_data = {"user_or_bot": validation_result, "api_key": api_key, "tool_group": tool_group}
        context_token = mcp_auth_context.set(auth_data)
        try:
            await MiddlewareHelper.log_api_key_usage(self.app, scope, receive, send, service)
        finally:
            mcp_auth_context.reset(context_token)
