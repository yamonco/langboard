import asyncio
import sys
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Any
import pytest


def test_production_defaults_enable_protection_without_global_wildcards(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Production defaults allow only derived public and internal API hosts."""

    module, env = _load_server(monkeypatch)
    env.API_URL = "https://api.example.test:8443/base"
    env.PUBLIC_UI_URL = "https://board.example.test"
    env.API_HOST = "langboard_api"
    env.API_PORT = 5381
    env.ENVIRONMENT = "production"

    settings = module._get_transport_security_settings()

    assert settings.enable_dns_rebinding_protection is True
    assert settings.allowed_hosts == [
        "api.example.test",
        "api.example.test:8443",
        "langboard_api",
        "langboard_api:5381",
    ]
    assert settings.allowed_origins == ["https://api.example.test:8443", "https://board.example.test"]
    assert "*" not in settings.allowed_hosts
    assert "*" not in settings.allowed_origins


def test_explicit_transport_allowlists_are_used_exactly(monkeypatch: pytest.MonkeyPatch) -> None:
    """Operations can reproduce proxy boundaries with explicit environment values."""

    module, env = _load_server(monkeypatch)
    env.MCP_ALLOWED_HOSTS = ["mcp.internal:8443"]
    env.MCP_ALLOWED_ORIGINS = ["https://agent.example.test"]

    settings = module._get_transport_security_settings()

    assert settings.allowed_hosts == env.MCP_ALLOWED_HOSTS
    assert settings.allowed_origins == env.MCP_ALLOWED_ORIGINS


@pytest.mark.parametrize(("setting", "value"), [("MCP_ALLOWED_HOSTS", "*"), ("MCP_ALLOWED_ORIGINS", "https://*")])
def test_global_transport_wildcard_is_rejected(
    monkeypatch: pytest.MonkeyPatch,
    setting: str,
    value: str,
) -> None:
    """An operator cannot accidentally restore the original global wildcard policy."""

    module, env = _load_server(monkeypatch)
    setattr(env, setting, [value])

    with pytest.raises(ValueError, match="global wildcard"):
        module._get_transport_security_settings()


@pytest.mark.parametrize(
    ("active", "tools", "error"),
    [
        (False, ["runtime_contract"], "inactive"),
        (True, [], "not allowed"),
    ],
)
def test_runtime_wrapper_rejects_inactive_or_nonmember_group_before_handler(
    monkeypatch: pytest.MonkeyPatch,
    active: bool,
    tools: list[str],
    error: str,
) -> None:
    """The native MCP wrapper independently enforces group activation and membership."""

    module, _ = _load_server(monkeypatch)
    handler_called = False

    def handler() -> dict[str, bool]:
        nonlocal handler_called
        handler_called = True
        return {"called": True}

    module.McpTool.get_tool = staticmethod(
        lambda tool_name: {
            "accessible_type": "user",
            "description": "runtime contract",
            "exclude": [],
            "handler": handler,
        }
        if tool_name == "runtime_contract"
        else None
    )
    group = module.McpToolGroup()
    group.activated_at = object() if active else None
    group.tools = tools
    module.mcp_auth_context = SimpleNamespace(get=lambda: {"user_or_bot": module.User(), "tool_group": group})
    wrapper = module.McpServer()._wrap_tool("runtime_contract", handler)

    with pytest.raises(PermissionError, match=error):
        asyncio.run(wrapper())

    assert handler_called is False


def _load_server(monkeypatch: pytest.MonkeyPatch) -> tuple[ModuleType, SimpleNamespace]:
    env = SimpleNamespace(
        API_HOST="localhost",
        API_PORT=5381,
        API_URL="http://localhost:5381",
        ENVIRONMENT="development",
        MCP_ALLOWED_HOSTS=[],
        MCP_ALLOWED_ORIGINS=[],
        PROJECT_NAME="langboard",
        PUBLIC_UI_URL="http://localhost:5173",
    )

    class TransportSecuritySettings:
        def __init__(
            self,
            *,
            enable_dns_rebinding_protection: bool,
            allowed_hosts: list[str],
            allowed_origins: list[str],
        ) -> None:
            self.enable_dns_rebinding_protection = enable_dns_rebinding_protection
            self.allowed_hosts = allowed_hosts
            self.allowed_origins = allowed_origins

    def class_instance() -> Any:
        return lambda target: target

    _set_package(monkeypatch, "langboard_shared")
    _set_package(monkeypatch, "langboard_shared.core")
    _set_module(monkeypatch, "langboard_shared.core.types", Factory=object)
    _set_package(monkeypatch, "langboard_shared.core.utils")
    _set_module(monkeypatch, "langboard_shared.core.utils.decorators", class_instance=class_instance)
    _set_package(monkeypatch, "langboard_shared.domain")
    user_model = type("User", (), {})
    _set_module(
        monkeypatch,
        "langboard_shared.domain.models",
        Bot=type("Bot", (), {}),
        McpToolGroup=type("McpToolGroup", (), {}),
        User=user_model,
    )
    services = _set_package(monkeypatch, "langboard_shared.domain.services")
    services.DomainService = type("DomainService", (), {})
    _set_module(monkeypatch, "langboard_shared.Env", Env=env)
    _set_package(monkeypatch, "langboard_shared.infrastructure")
    _set_module(monkeypatch, "langboard_shared.infrastructure.repositories", Repository=type("Repository", (), {}))
    _set_package(monkeypatch, "mcp")
    _set_package(monkeypatch, "mcp.server")

    class FastMCP:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            pass

    _set_module(monkeypatch, "mcp.server.fastmcp", FastMCP=FastMCP)
    _set_module(
        monkeypatch,
        "mcp.server.transport_security",
        TransportSecuritySettings=TransportSecuritySettings,
    )
    _set_module(monkeypatch, "pydantic", BaseModel=type("BaseModel", (), {}))
    _set_package(monkeypatch, "langboard")
    _set_package(monkeypatch, "langboard.mcp_integration")
    _set_package(monkeypatch, "langboard.mcp_tools")
    _set_module(
        monkeypatch,
        "langboard.mcp_tools.RoleChecker",
        McpRoleChecker=type("McpRoleChecker", (), {}),
    )
    _set_module(
        monkeypatch,
        "langboard.middlewares",
        DynamicSseMiddleware=object,
        McpAuthMiddleware=object,
    )
    _set_module(
        monkeypatch,
        "langboard.middlewares.McpAuthMiddleware",
        mcp_auth_context=SimpleNamespace(get=lambda: None),
    )
    _set_module(monkeypatch, "langboard.mcp_integration.Tool", McpTool=type("McpTool", (), {}))

    subject = Path(__file__).parents[2] / "langboard" / "mcp_integration" / "Server.py"
    spec = spec_from_file_location("langboard.mcp_integration.Server", subject)
    assert spec is not None and spec.loader is not None
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    return module, env


def _set_package(monkeypatch: pytest.MonkeyPatch, name: str) -> ModuleType:
    module = _set_module(monkeypatch, name)
    module.__path__ = []
    return module


def _set_module(monkeypatch: pytest.MonkeyPatch, name: str, **attributes: Any) -> ModuleType:
    module = ModuleType(name)
    module.__dict__.update(attributes)
    monkeypatch.setitem(sys.modules, name, module)
    return module
