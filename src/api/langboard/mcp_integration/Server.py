import traceback
from collections.abc import Callable
from enum import Enum
from inspect import Parameter, iscoroutinefunction, signature
from types import UnionType
from typing import Any, TypeGuard, Union, get_args, get_origin
from urllib.parse import urlsplit
from langboard_shared.core.types import Factory
from langboard_shared.core.utils.decorators import class_instance
from langboard_shared.domain.models import Bot, McpToolGroup, User
from langboard_shared.domain.services import DomainService
from langboard_shared.Env import Env
from langboard_shared.infrastructure.repositories import Repository
from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from pydantic import BaseModel
from ..mcp_tools.RoleChecker import McpRoleChecker
from ..middlewares import DynamicSseMiddleware, McpAuthMiddleware
from ..middlewares.McpAuthMiddleware import mcp_auth_context
from .Tool import McpTool


@class_instance()
class McpServer:
    def __init__(self):
        self.mcp = FastMCP(Env.PROJECT_NAME)
        self._streamable_http_app = None

    def get_http_app(self):
        try:
            security_settings = _get_transport_security_settings()

            app = FastMCP(
                Env.PROJECT_NAME,
                transport_security=security_settings,
                streamable_http_path="/stream",
                stateless_http=True,
            )

            all_tools = McpTool.get_tools()
            for tool_name, tool_data in all_tools.items():
                handler = tool_data["handler"]
                wrapper = self._wrap_tool(tool_name, handler)
                app.add_tool(wrapper, name=tool_name, description=tool_data["description"])

            http_app = app.streamable_http_app()
            http_app.add_middleware(DynamicSseMiddleware)
            http_app.add_middleware(McpAuthMiddleware)

            return http_app, app
        except Exception:
            traceback.print_exc()
            return None

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
            tool_group: McpToolGroup | None = auth_data.get("tool_group") if auth_data else None

            if not self._validate_auth(auth_value, tool_name):
                raise PermissionError("Authentication required")

            if not tool_group:
                raise PermissionError("MCP tool group not validated")

            if tool_group.activated_at is None:
                raise PermissionError("MCP tool group is inactive")

            if tool_name not in tool_group.tools:
                raise PermissionError(f"Tool '{tool_name}' not allowed for this tool group")

            if not self._validate_role(auth_value, handler, **kwargs):
                raise PermissionError("Insufficient permissions")

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
                    raise PermissionError("User authentication required")
            elif Bot in args:
                if isinstance(auth_value, Bot):
                    kwargs[param_name] = auth_value
                else:
                    raise PermissionError("Bot authentication required")
        elif annotation == User:
            if isinstance(auth_value, User):
                kwargs[param_name] = auth_value
            else:
                raise PermissionError("User authentication required")
        elif annotation == Bot:
            if isinstance(auth_value, Bot):
                kwargs[param_name] = auth_value
            else:
                raise PermissionError("Bot authentication required")
        elif annotation == DomainService:
            factory = DomainService()
            kwargs[param_name] = factory
        elif annotation == Repository:
            factory = Repository()
            kwargs[param_name] = factory
        elif isinstance(annotation, type) and issubclass(annotation, BaseModel):
            kwargs[param_name] = annotation.model_validate(kwargs.get(param_name))
        elif isinstance(annotation, type) and issubclass(annotation, Enum):
            value = kwargs.get(param_name)
            if value is not None:
                try:
                    kwargs[param_name] = annotation(value)
                except Exception:
                    try:
                        kwargs[param_name] = annotation[value]
                    except Exception:
                        raise ValueError(f"Invalid value for enum '{annotation.__name__}': {value}")

        return kwargs, factory


def _get_transport_security_settings() -> TransportSecuritySettings:
    allowed_hosts = Env.MCP_ALLOWED_HOSTS or _get_default_allowed_hosts()
    allowed_origins = Env.MCP_ALLOWED_ORIGINS or _get_default_allowed_origins()
    _reject_global_wildcards(allowed_hosts, "MCP_ALLOWED_HOSTS")
    _reject_global_wildcards(allowed_origins, "MCP_ALLOWED_ORIGINS")
    return TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=allowed_hosts,
        allowed_origins=allowed_origins,
    )


def _get_default_allowed_hosts() -> list[str]:
    hosts = {
        _url_host(Env.API_URL),
        _url_hostname(Env.API_URL),
        Env.API_HOST,
        f"{Env.API_HOST}:{Env.API_PORT}",
    }
    if Env.ENVIRONMENT == "development":
        hosts.update(
            {"localhost", "localhost:*", "127.0.0.1", "127.0.0.1:*", "[::1]", "[::1]:*", "testserver"}
        )
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
