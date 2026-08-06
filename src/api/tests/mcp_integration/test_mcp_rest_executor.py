import asyncio
import sys
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Any
import pytest
from pydantic import BaseModel


@pytest.mark.parametrize(
    ("active", "tools"),
    [
        (False, ["execute_contract"]),
        (True, []),
    ],
)
def test_inactive_or_nonmember_group_stops_before_body_and_handler(
    monkeypatch: pytest.MonkeyPatch,
    active: bool,
    tools: list[str],
) -> None:
    """REST execution rejects unusable groups before parsing or invoking the tool."""

    contract = _load_mcp_api(monkeypatch)
    contract.state.group = SimpleNamespace(
        activated_at=object() if active else None,
        tools=tools,
        user_id=None,
    )
    request = contract.Request(contract.User(7), {"value": "payload"})

    with pytest.raises(contract.Forbidden):
        asyncio.run(contract.module.execute_mcp_tool("execute_contract", request))

    assert request.json_calls == 0
    assert contract.state.role_calls == []
    assert contract.state.handler_calls == []
    assert contract.state.services[-1].closed is True
    assert contract.state.repositories[-1].closed is True


def test_active_member_group_executes_after_role_check(monkeypatch: pytest.MonkeyPatch) -> None:
    """An active group member reaches the handler with the shared service injected."""

    contract = _load_mcp_api(monkeypatch)
    contract.state.group = SimpleNamespace(activated_at=object(), tools=["execute_contract"], user_id=None)
    request = contract.Request(contract.User(7), {"value": "payload"})

    response = asyncio.run(contract.module.execute_mcp_tool("execute_contract", request))

    assert response.content == {"result": {"value": "payload"}}
    assert contract.state.role_calls == [(contract.handler, request.scope["auth"], {"value": "payload"})]
    assert len(contract.state.handler_calls) == 1
    assert contract.state.services[-1].closed is True
    assert contract.state.repositories[-1].closed is True


def test_typed_results_are_recursively_dumped_as_json(monkeypatch: pytest.MonkeyPatch) -> None:
    """Nested Pydantic outputs remain structured JSON instead of becoming repr strings."""

    contract = _load_mcp_api(monkeypatch)

    class Card(BaseModel):
        uid: str

    class Result(BaseModel):
        card: Card

    value = {"page": [Result(card=Card(uid="c1"))]}

    assert contract.module.serialize_mcp_result(value) == {"page": [{"card": {"uid": "c1"}}]}


def test_user_rest_route_rejects_bot_only_tool(monkeypatch: pytest.MonkeyPatch) -> None:
    """The user-only REST facade cannot invoke a future bot-only MCP tool."""

    contract = _load_mcp_api(monkeypatch)
    contract.state.group = SimpleNamespace(activated_at=object(), tools=["execute_contract"], user_id=None)
    contract.state.tool["accessible_type"] = "bot"
    request = contract.Request(contract.User(7), {"value": "payload"})

    with pytest.raises(contract.Forbidden):
        asyncio.run(contract.module.execute_mcp_tool("execute_contract", request))

    assert request.json_calls == 0
    assert contract.state.handler_calls == []


def _load_mcp_api(monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
    state = SimpleNamespace(
        group=None,
        handler_calls=[],
        repositories=[],
        role_allowed=True,
        role_calls=[],
        services=[],
        tool=None,
    )

    class User:
        def __init__(self, user_id: int) -> None:
            self.id = user_id

    class Request:
        def __init__(self, user: User, body: Any) -> None:
            self.headers = {"X-MCP-Tool-Group-UID": "group-a"}
            self.scope = {"auth": user}
            self.body = body
            self.json_calls = 0

        async def json(self) -> Any:
            self.json_calls += 1
            return self.body

    class JsonResponse:
        def __init__(self, content: Any = None, status_code: int = 200) -> None:
            self.content = content
            self.status_code = status_code

    class Forbidden(Exception):
        pass

    class ApiException:
        BadRequest_400 = type("BadRequest", (Exception,), {})
        Forbidden_403 = Forbidden
        NotFound_404 = type("NotFound", (Exception,), {})
        Unauthorized_401 = type("Unauthorized", (Exception,), {})

    class _Decorator:
        @staticmethod
        def add(*args: Any, **kwargs: Any) -> Any:
            return lambda method: method

    class _Api:
        get = _Decorator.add
        post = _Decorator.add

    class AppRouter:
        api = _Api()
        schema = _Decorator.add

    class Repository:
        def __init__(self) -> None:
            self.closed = False
            state.repositories.append(self)

        def close(self) -> None:
            self.closed = True

    class McpToolGroupService:
        def get_by_id_like(self, group_uid: str) -> Any:
            assert group_uid == "group-a"
            return state.group

    class DomainService:
        def __init__(self) -> None:
            self.closed = False
            self.mcp_tool_group = McpToolGroupService()
            state.services.append(self)

        def initialize(self, repository: Repository) -> None:
            self.repository = repository

        def close(self) -> None:
            self.closed = True

    class McpRoleChecker:
        def __init__(self, service: DomainService) -> None:
            self.service = service

        def check_permission(self, handler: Any, user: User, arguments: dict[str, Any]) -> bool:
            state.role_calls.append((handler, user, arguments.copy()))
            return state.role_allowed

    def handler(value: str, service: DomainService) -> dict[str, str]:
        state.handler_calls.append((value, service))
        return {"value": value}

    state.tool = {"handler": handler, "accessible_type": "user"}

    class McpTool:
        @staticmethod
        def get_tools() -> dict[str, Any]:
            return {"execute_contract": state.tool}

        @staticmethod
        def get_tool(tool_name: str) -> dict[str, Any] | None:
            return state.tool if tool_name == "execute_contract" else None

    _set_module(monkeypatch, "fastapi", Request=Request)
    _set_package(monkeypatch, "langboard_shared")
    _set_package(monkeypatch, "langboard_shared.core")
    _set_module(monkeypatch, "langboard_shared.core.filter", AuthFilter=_Decorator)
    _set_module(
        monkeypatch,
        "langboard_shared.core.security",
        AuthSecurity=SimpleNamespace(MCP_TOOL_GROUP_UID_HEADER="X-MCP-Tool-Group-UID"),
    )
    _set_module(
        monkeypatch,
        "langboard_shared.core.routing",
        ApiErrorCode=SimpleNamespace(
            AU1001="unauthorized", NF1004="tool", NF3006="group", PE1001="permission", VA0000="invalid"
        ),
        ApiException=ApiException,
        ApiPermission=SimpleNamespace(Delete="delete", Read="read"),
        AppRouter=AppRouter,
        JsonResponse=JsonResponse,
    )
    _set_package(monkeypatch, "langboard_shared.domain")
    _set_module(monkeypatch, "langboard_shared.domain.models", McpRole=object, User=User)
    _set_module(
        monkeypatch,
        "langboard_shared.domain.models.McpRole",
        McpRoleAction=SimpleNamespace(Read="read"),
    )
    services_package = _set_package(monkeypatch, "langboard_shared.domain.services")
    services_package.DomainService = DomainService
    _set_module(monkeypatch, "langboard_shared.filter", RoleFilter=_Decorator)
    _set_package(monkeypatch, "langboard_shared.infrastructure")
    _set_module(monkeypatch, "langboard_shared.infrastructure.repositories", Repository=Repository)
    _set_module(monkeypatch, "langboard_shared.security", RoleFinder=SimpleNamespace(mcp=lambda: None))
    _set_package(monkeypatch, "langboard")
    _set_package(monkeypatch, "langboard.routes")
    _set_package(monkeypatch, "langboard.routes.mcp")
    _set_module(monkeypatch, "langboard.mcp_integration", McpTool=McpTool)
    _set_package(monkeypatch, "langboard.mcp_tools")
    _set_module(monkeypatch, "langboard.mcp_tools.RoleChecker", McpRoleChecker=McpRoleChecker)

    subject = Path(__file__).parents[2] / "langboard" / "routes" / "mcp" / "McpApi.py"
    spec = spec_from_file_location("langboard.routes.mcp.McpApi", subject)
    assert spec is not None and spec.loader is not None
    module = module_from_spec(spec)
    spec.loader.exec_module(module)

    return SimpleNamespace(
        Forbidden=Forbidden,
        Request=Request,
        User=User,
        handler=handler,
        module=module,
        state=state,
    )


def _set_package(monkeypatch: pytest.MonkeyPatch, name: str) -> ModuleType:
    module = _set_module(monkeypatch, name)
    module.__path__ = []
    return module


def _set_module(monkeypatch: pytest.MonkeyPatch, name: str, **attributes: Any) -> ModuleType:
    module = ModuleType(name)
    module.__dict__.update(attributes)
    monkeypatch.setitem(sys.modules, name, module)
    return module
