import sys
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Any, ClassVar
import pytest


def test_user_role_metadata_tuple_is_applied_exactly(monkeypatch: pytest.MonkeyPatch) -> None:
    """User authorization receives actions and finder, not the metadata tuple itself."""

    contract = _load_role_checker(monkeypatch)
    contract.RoleSecurity.decision = False
    user = contract.User(7)
    arguments = {"project_uid": "project-a"}

    allowed = contract.checker.check_permission(contract.handler, user, arguments)

    assert allowed is False
    assert contract.RoleSecurity.calls == [(contract.ProjectRole, user.id, arguments, ["read"], contract.finder)]


def test_admin_only_short_circuits_when_filter_allows_it(monkeypatch: pytest.MonkeyPatch) -> None:
    """A filter can explicitly require even an administrator to hold a role."""

    contract = _load_role_checker(monkeypatch)
    admin = contract.User(1, is_admin=True)

    assert contract.checker.check_permission(contract.handler, admin, {"project_uid": "project-a"}) is True
    assert contract.RoleSecurity.calls == []

    contract.McpRoleFilter.metadata = (contract.ProjectRole, ["read"], contract.finder, False)
    contract.RoleSecurity.decision = False

    assert contract.checker.check_permission(contract.handler, admin, {"project_uid": "project-a"}) is False
    assert len(contract.RoleSecurity.calls) == 1


def test_bot_requires_scope_for_exact_project(monkeypatch: pytest.MonkeyPatch) -> None:
    """A project-scoped MCP tool only accepts bots assigned to that project."""

    contract = _load_role_checker(monkeypatch)
    bot = contract.Bot(9)
    contract.bot_service.allowed = False

    assert contract.checker.check_permission(contract.handler, bot, {"project_uid": "project-a"}) is False

    contract.bot_service.allowed = True
    assert contract.checker.check_permission(contract.handler, bot, {"project_uid": "project-a"}) is True
    assert contract.bot_service.calls[-1] == (bot, "project-a")


@pytest.mark.parametrize("project_uid", [None, "", 123])
def test_bot_missing_string_project_uid_fails_closed(monkeypatch: pytest.MonkeyPatch, project_uid: Any) -> None:
    """Malformed or absent project identifiers never bypass bot scoping."""

    contract = _load_role_checker(monkeypatch)

    assert contract.checker.check_permission(contract.handler, contract.Bot(9), {"project_uid": project_uid}) is False
    assert contract.bot_service.calls == []


def _load_role_checker(monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
    class User:
        def __init__(self, user_id: int, is_admin: bool = False) -> None:
            self.id = user_id
            self.is_admin = is_admin

    class Bot:
        def __init__(self, bot_id: int) -> None:
            self.id = bot_id

    class ProjectRole:
        pass

    class BotService:
        def __init__(self) -> None:
            self.calls: list[tuple[Bot, str]] = []
            self.allowed = False

        def has_project_access(self, bot: Bot, project_uid: str) -> bool:
            self.calls.append((bot, project_uid))
            return self.allowed

    bot_service = BotService()

    class DomainService:
        def __init__(self) -> None:
            self.bot = bot_service

    class RoleSecurity:
        calls: ClassVar[list[tuple[Any, ...]]] = []
        decision = True

        def __init__(self, role_model: type) -> None:
            self.role_model = role_model

        def is_authorized(
            self,
            user_id: int,
            arguments: dict[str, Any],
            actions: list[str],
            finder: Any,
        ) -> bool:
            self.calls.append((self.role_model, user_id, arguments, actions, finder))
            return self.decision

    def finder(query: Any, arguments: dict[str, Any], user_id: int) -> Any:
        return query

    def handler() -> None:
        return None

    class McpRoleFilter:
        metadata = (ProjectRole, ["read"], finder, True)

        @classmethod
        def exists(cls, method: Any) -> bool:
            return method is handler

        @classmethod
        def get_filtered(cls, method: Any) -> tuple[Any, ...]:
            assert method is handler
            return cls.metadata

    _set_package(monkeypatch, "langboard_shared")
    _set_package(monkeypatch, "langboard_shared.domain")
    _set_module(
        monkeypatch,
        "langboard_shared.domain.models",
        Bot=Bot,
        ProjectRole=ProjectRole,
        User=User,
    )
    _set_package(monkeypatch, "langboard_shared.domain.services")
    _set_module(monkeypatch, "langboard_shared.domain.services.DomainService", DomainService=DomainService)
    _set_module(monkeypatch, "langboard_shared.security", RoleSecurity=RoleSecurity)
    _set_package(monkeypatch, "langboard")
    _set_package(monkeypatch, "langboard.mcp_tools")
    _set_package(monkeypatch, "langboard.mcp_integration")
    _set_module(monkeypatch, "langboard.mcp_integration.RoleFilter", McpRoleFilter=McpRoleFilter)

    subject = Path(__file__).parents[2] / "langboard" / "mcp_tools" / "RoleChecker.py"
    spec = spec_from_file_location("langboard.mcp_tools.RoleChecker", subject)
    assert spec is not None and spec.loader is not None
    module = module_from_spec(spec)
    spec.loader.exec_module(module)

    return SimpleNamespace(
        Bot=Bot,
        McpRoleFilter=McpRoleFilter,
        ProjectRole=ProjectRole,
        RoleSecurity=RoleSecurity,
        User=User,
        checker=module.McpRoleChecker(DomainService()),
        bot_service=bot_service,
        finder=finder,
        handler=handler,
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
