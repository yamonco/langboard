import sys
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from types import ModuleType
from typing import Any
import pytest


def test_project_scoped_activity_tools_require_project_read(monkeypatch: pytest.MonkeyPatch) -> None:
    """All project activity variants register Read while the current-user query remains personal."""

    registrations: dict[str, tuple[Any, list[str], Any]] = {}
    project_role = type("ProjectRole", (), {})
    project_finder = object()

    class McpRoleFilter:
        @staticmethod
        def add(role_model: Any, actions: list[str], role_finder: Any) -> Any:
            def decorator(method: Any) -> Any:
                registrations[method.__name__] = (role_model, actions, role_finder)
                return method

            return decorator

    class McpTool:
        @staticmethod
        def add(*args: Any, **kwargs: Any) -> Any:
            return lambda method: method

    class TimeBasedPagination:
        def __init__(self, **kwargs: Any) -> None:
            self.values = kwargs

    _set_package(monkeypatch, "langboard_shared")
    _set_package(monkeypatch, "langboard_shared.core")
    _set_module(monkeypatch, "langboard_shared.core.schema", TimeBasedPagination=TimeBasedPagination)
    _set_package(monkeypatch, "langboard_shared.domain")
    _set_module(
        monkeypatch,
        "langboard_shared.domain.models",
        ProjectRole=project_role,
        User=type("User", (), {}),
    )
    _set_module(
        monkeypatch,
        "langboard_shared.domain.models.ProjectRole",
        ProjectRoleAction=type("ProjectRoleAction", (), {"Read": "read"}),
    )
    _set_package(monkeypatch, "langboard_shared.domain.services")
    _set_module(
        monkeypatch,
        "langboard_shared.domain.services.DomainService",
        DomainService=type("DomainService", (), {}),
    )
    _set_module(
        monkeypatch, "langboard_shared.security", RoleFinder=type("RoleFinder", (), {"project": project_finder})
    )
    _set_package(monkeypatch, "langboard")
    _set_package(monkeypatch, "langboard.mcp_tools")
    _set_module(
        monkeypatch,
        "langboard.mcp_integration",
        McpRoleFilter=McpRoleFilter,
        McpTool=McpTool,
    )

    subject = Path(__file__).parents[2] / "langboard" / "mcp_tools" / "ActivityMcp.py"
    spec = spec_from_file_location("langboard.mcp_tools.ActivityMcp", subject)
    assert spec is not None and spec.loader is not None
    module = module_from_spec(spec)
    spec.loader.exec_module(module)

    expected = {
        "get_project_activities",
        "get_project_column_activities",
        "get_card_activities",
        "get_wiki_activities",
    }
    assert set(registrations) == expected
    assert "get_current_user_activities" not in registrations
    assert all(metadata == (project_role, ["read"], project_finder) for metadata in registrations.values())


def _set_package(monkeypatch: pytest.MonkeyPatch, name: str) -> ModuleType:
    module = _set_module(monkeypatch, name)
    module.__path__ = []
    return module


def _set_module(monkeypatch: pytest.MonkeyPatch, name: str, **attributes: Any) -> ModuleType:
    module = ModuleType(name)
    module.__dict__.update(attributes)
    monkeypatch.setitem(sys.modules, name, module)
    return module
