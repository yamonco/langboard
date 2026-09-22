import os
import re
import subprocess
import sys
from types import SimpleNamespace
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pytest import MonkeyPatch
from starlette.middleware import Middleware


os.environ.setdefault("PROJECT_NAME", "langboard")

from langboard.App import App  # noqa: E402
from langboard.Loader import ModuleLoader  # noqa: E402
from langboard.middlewares import ApiAuthMiddleware, ChatUploadConcurrencyMiddleware, RoleMiddleware  # noqa: E402
from langboard_shared.core.routing import AppRouter  # noqa: E402
from langboard_shared.FastAPIAppConfig import FastAPIAppConfigModel  # noqa: E402


def _create_test_app() -> App:
    app = App.__new__(App)
    app.api = FastAPI()
    app.config = FastAPIAppConfigModel(
        host="localhost",
        port=5381,
        lifespan="auto",
        workers=1,
        is_restarting=True,
    )
    return app


def _find_middleware(app: App, middleware_class: object) -> Middleware:
    return next(middleware for middleware in app.api.user_middleware if middleware.cls is middleware_class)


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
    app = _create_test_app()

    app._init_api_middlewares()

    assert _find_middleware(app, ApiAuthMiddleware).kwargs["routes"] is AppRouter.api.routes
    assert _find_middleware(app, RoleMiddleware).kwargs["routes"] is AppRouter.api.routes


def test_cors_wraps_chat_upload_concurrency_rejections(monkeypatch: MonkeyPatch) -> None:
    monkeypatch.setattr(ModuleLoader, "load", lambda *args, **kwargs: {})
    app = _create_test_app()

    app._init_api_middlewares()

    cors_index = next(index for index, middleware in enumerate(app.api.user_middleware) if middleware.cls is CORSMiddleware)
    upload_index = next(
        index
        for index, middleware in enumerate(app.api.user_middleware)
        if middleware.cls is ChatUploadConcurrencyMiddleware
    )
    assert cors_index < upload_index


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
    app = _create_test_app()

    app._init_api_middlewares()

    cors = _find_middleware(app, CORSMiddleware)
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
    app = _create_test_app()

    app._init_api_middlewares()

    cors = _find_middleware(app, CORSMiddleware)
    origin_regex = cors.kwargs["allow_origin_regex"]
    assert isinstance(origin_regex, str)
    assert re.fullmatch(origin_regex, "http://localhost:49152")
    assert not re.fullmatch(origin_regex, "https://example.test")
