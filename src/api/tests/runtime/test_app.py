import os
import re
import subprocess
import sys
from types import SimpleNamespace
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pytest import MonkeyPatch


os.environ.setdefault("PROJECT_NAME", "langboard")

from langboard.App import App  # noqa: E402
from langboard.Loader import ModuleLoader  # noqa: E402
from langboard.middlewares import ApiAuthMiddleware, RoleMiddleware  # noqa: E402
from langboard_shared.core.routing import AppRouter  # noqa: E402


def test_activity_tasks_import_without_cycle() -> None:
    """Match the broker's task discovery order in a clean interpreter."""

    result = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "from langboard_shared.tasks.activities import "
                "UserActivityTask, ProjectActivityTask, ProjectWikiActivityTask, "
                "CardActivityTask, CardAttachmentActivityTask"
            ),
        ],
        capture_output=True,
        check=False,
        env={**os.environ, "PROJECT_NAME": "langboard"},
        text=True,
    )

    assert result.returncode == 0, result.stderr


def test_project_email_task_imports_first_without_cycle() -> None:
    """The notification worker can discover its task before activity modules."""

    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import langboard_shared.tasks.notifications.ProjectEmailNotificationTask",
        ],
        capture_output=True,
        check=False,
        env={**os.environ, "PROJECT_NAME": "langboard"},
        text=True,
    )

    assert result.returncode == 0, result.stderr


def test_authorization_middlewares_use_original_api_routes(monkeypatch: MonkeyPatch) -> None:
    """Keep authorization compatible with FastAPI's included-router wrapper."""
    monkeypatch.setenv("PROJECT_NAME", "langboard")

    monkeypatch.setattr(ModuleLoader, "load", lambda *args, **kwargs: {})
    app = App.__new__(App)
    app.api = FastAPI()
    app.config = SimpleNamespace(is_restarting=True)

    app._init_api_middlewares()

    authorization_middlewares = {
        middleware.cls: middleware
        for middleware in app.api.user_middleware
        if middleware.cls in {ApiAuthMiddleware, RoleMiddleware}
    }
    assert authorization_middlewares[ApiAuthMiddleware].kwargs["routes"] is AppRouter.api.routes
    assert authorization_middlewares[RoleMiddleware].kwargs["routes"] is AppRouter.api.routes


def test_production_cors_uses_configured_mcp_origins(monkeypatch: MonkeyPatch) -> None:
    """Production accepts only the UI and explicitly configured MCP clients."""

    monkeypatch.setattr(ModuleLoader, "load", lambda *args, **kwargs: {})
    monkeypatch.setitem(
        App._init_api_middlewares.__globals__,
        "Env",
        SimpleNamespace(
            ENVIRONMENT="production",
            MCP_ALLOWED_ORIGINS=["http://localhost:6274", "https://mcp.example.test"],
            PUBLIC_UI_URL="https://board.example.test",
        ),
    )
    app = App.__new__(App)
    app.api = FastAPI()
    app.config = SimpleNamespace(is_restarting=True)

    app._init_api_middlewares()

    cors = next(middleware for middleware in app.api.user_middleware if middleware.cls is CORSMiddleware)
    assert cors.kwargs["allow_origins"] == [
        "https://board.example.test",
        "http://localhost:6274",
        "https://mcp.example.test",
    ]
    assert cors.kwargs["allow_origin_regex"] is None


def test_development_cors_accepts_local_clients_on_any_port(monkeypatch: MonkeyPatch) -> None:
    monkeypatch.setattr(ModuleLoader, "load", lambda *args, **kwargs: {})
    monkeypatch.setitem(
        App._init_api_middlewares.__globals__,
        "Env",
        SimpleNamespace(
            ENVIRONMENT="development",
            MCP_ALLOWED_ORIGINS=[],
            PUBLIC_UI_URL="http://localhost:5173",
        ),
    )
    app = App.__new__(App)
    app.api = FastAPI()
    app.config = SimpleNamespace(is_restarting=True)

    app._init_api_middlewares()

    cors = next(middleware for middleware in app.api.user_middleware if middleware.cls is CORSMiddleware)
    origin_regex = cors.kwargs["allow_origin_regex"]
    assert origin_regex is not None
    assert re.fullmatch(origin_regex, "http://localhost:49152")
    assert not re.fullmatch(origin_regex, "https://example.test")
