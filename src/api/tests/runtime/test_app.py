from types import SimpleNamespace
from fastapi import FastAPI
from pytest import MonkeyPatch


def test_authorization_middlewares_use_original_api_routes(monkeypatch: MonkeyPatch) -> None:
    """Keep authorization compatible with FastAPI's included-router wrapper."""
    monkeypatch.setenv("PROJECT_NAME", "langboard")

    from langboard.App import App
    from langboard.Loader import ModuleLoader
    from langboard.middlewares import ApiAuthMiddleware, RoleMiddleware
    from langboard_shared.core.routing import AppRouter

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
