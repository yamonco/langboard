from collections.abc import Callable
from inspect import Parameter, iscoroutinefunction, signature
from types import UnionType
from typing import Any, TypeGuard, Union, get_args, get_origin
from urllib.parse import urlsplit
from fastmcp import FastMCP
from fastmcp.exceptions import AuthorizationError
from fastmcp.tools import Tool
from langboard_shared.core.types import Factory
from langboard_shared.core.utils.decorators import class_instance
from langboard_shared.domain.models import Bot, User
from langboard_shared.domain.services import DomainService
from langboard_shared.Env import Env
from langboard_shared.infrastructure.repositories import Repository
from ..mcp_tools.RoleChecker import McpRoleChecker
from ..middlewares import McpAuthMiddleware
from ..middlewares.McpAuthMiddleware import mcp_auth_context
from .Tool import McpTool
from .ToolGroupMiddleware import ToolGroupMiddleware


def _create_fastmcp() -> FastMCP:
    return FastMCP(
        Env.PROJECT_NAME,
        strict_input_validation=True,
        mask_error_details=True,
        middleware=[ToolGroupMiddleware()],
    )


@class_instance()
class McpServer:
    def __init__(self):
        self.mcp = _create_fastmcp()
        self._streamable_http_app = None

    def get_http_app(self) -> tuple[Any, FastMCP]:
        """Build the MCP transport or fail application startup."""

        allowed_hosts, allowed_origins = _get_transport_security_allowlists()
        app = _create_fastmcp()

        all_tools = McpTool.get_tools()
        for tool_name, tool_data in all_tools.items():
            handler = tool_data["handler"]
            wrapper = self._wrap_tool(tool_name, handler)
            app.add_tool(Tool.from_function(wrapper, name=tool_name, description=tool_data["description"]))

        http_app = app.http_app(
            path="/stream",
            stateless_http=True,
            allowed_hosts=allowed_hosts,
            allowed_origins=allowed_origins,
        )
        http_app.add_middleware(McpAuthMiddleware)

        self.mcp = app
        return http_app, app

    def _wrap_tool(self, tool_name: str, handler: Callable):
        sig = signature(handler)
        tool_data = McpTool.get_tool(tool_name)
        exclude = tool_data.get("exclude", []) if tool_data else []

        # Filter out excluded parameters from the signature
        filtered_params = [param for name, param in sig.parameters.items() if name not in exclude]
        filtered_sig = sig.replace(parameters=filtered_params)

        async def wrapper(**kwargs):
            auth_data = mcp_auth_context.get()
            auth_value: User | Bot | None = auth_data.get("user_or_bot") if auth_data else None

            if not self._validate_auth(auth_value, tool_name):
                raise AuthorizationError("Authentication required")

            if not self._validate_role(auth_value, handler, **kwargs):
                raise AuthorizationError("Insufficient permissions")

            factories: list[Factory] = []
            for param_name, param in sig.parameters.items():
                kwargs, factory = self._inject_kwargs(param_name, param, auth_value, kwargs)
                if factory:
                    factories.append(factory)

            try:
                return await handler(**kwargs) if iscoroutinefunction(handler) else handler(**kwargs)
            finally:
                for factory in factories:
                    factory.close()

        # Use the filtered signature so FastMCP only sees the non-excluded parameters
        wrapper.__signature__ = filtered_sig

        return wrapper

    def _validate_auth(self, user_or_bot: User | Bot | None, tool_name: str) -> TypeGuard[User | Bot]:
        if not isinstance(user_or_bot, (User, Bot)):
            return False

        tool_data = McpTool.get_tool(tool_name)
        if not tool_data:
            return False

        accessible_type = tool_data.get("accessible_type", "all")
        if accessible_type == "all":
            return True
        elif accessible_type == "user" and isinstance(user_or_bot, User):
            return True
        elif accessible_type == "bot" and isinstance(user_or_bot, Bot):
            return True

        return False

    def _validate_role(
        self,
        user_or_bot: User | Bot | None,
        handler: Callable[..., Any],
        **kwargs: Any,
    ) -> bool:
        if not isinstance(user_or_bot, (User, Bot)):
            return False
        service = DomainService()
        try:
            return McpRoleChecker(service).check_permission(handler, user_or_bot, kwargs)
        finally:
            service.close()

    def _inject_kwargs(
        self, param_name: str, param: Parameter, auth_value: User | Bot, kwargs: dict
    ) -> tuple[dict, Factory | None]:
        annotation = param.annotation
        origin = get_origin(annotation)
        args = get_args(annotation)

        factory = None

        if origin is UnionType or origin is Union:
            if User in args and Bot in args:
                kwargs[param_name] = auth_value
            elif User in args:
                if isinstance(auth_value, User):
                    kwargs[param_name] = auth_value
                else:
                    raise AuthorizationError("User authentication required")
            elif Bot in args:
                if isinstance(auth_value, Bot):
                    kwargs[param_name] = auth_value
                else:
                    raise AuthorizationError("Bot authentication required")
        elif annotation == User:
            if isinstance(auth_value, User):
                kwargs[param_name] = auth_value
            else:
                raise AuthorizationError("User authentication required")
        elif annotation == Bot:
            if isinstance(auth_value, Bot):
                kwargs[param_name] = auth_value
            else:
                raise AuthorizationError("Bot authentication required")
        elif annotation == DomainService:
            factory = DomainService()
            kwargs[param_name] = factory
        elif annotation == Repository:
            factory = Repository()
            kwargs[param_name] = factory
        return kwargs, factory


def _get_transport_security_allowlists() -> tuple[list[str], list[str]]:
    allowed_hosts = Env.MCP_ALLOWED_HOSTS or _get_default_allowed_hosts()
    allowed_origins = Env.MCP_ALLOWED_ORIGINS or _get_default_allowed_origins()
    _reject_global_wildcards(allowed_hosts, "MCP_ALLOWED_HOSTS")
    _reject_global_wildcards(allowed_origins, "MCP_ALLOWED_ORIGINS")
    return allowed_hosts, allowed_origins


def _get_default_allowed_hosts() -> list[str]:
    hosts = {
        _url_host(Env.API_URL),
        _url_hostname(Env.API_URL),
        Env.API_HOST,
        f"{Env.API_HOST}:{Env.API_PORT}",
    }
    if Env.ENVIRONMENT == "development":
        hosts.update({"localhost", "localhost:*", "127.0.0.1", "127.0.0.1:*", "[::1]", "[::1]:*", "testserver"})
    return sorted(host for host in hosts if host)


def _get_default_allowed_origins() -> list[str]:
    origins = {_url_origin(Env.API_URL), _url_origin(Env.PUBLIC_UI_URL)}
    if Env.ENVIRONMENT == "development":
        origins.update({"http://localhost:*", "http://127.0.0.1:*", "http://[::1]:*"})
    return sorted(origin for origin in origins if origin)


def _url_host(url: str) -> str:
    return urlsplit(url).netloc


def _url_hostname(url: str) -> str:
    return urlsplit(url).hostname or ""


def _url_origin(url: str) -> str:
    parsed = urlsplit(url)
    return f"{parsed.scheme}://{parsed.netloc}" if parsed.scheme and parsed.netloc else ""


def _reject_global_wildcards(values: list[str], setting_name: str) -> None:
    unsafe_values = {"*", "http://*", "https://*"}
    if any(value in unsafe_values for value in values):
        raise ValueError(f"{setting_name} cannot contain a global wildcard")
