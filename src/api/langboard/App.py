from contextlib import asynccontextmanager
from json import loads as json_loads
from typing import Any, cast
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from langboard_shared.core.routing import AppExceptionHandlingRoute, AppRouter, BaseMiddleware
from langboard_shared.core.security import AuthSecurity, KeyVault
from langboard_shared.Env import Env
from langboard_shared.FastAPIAppConfig import FastAPIAppConfig
from .Constants import APP_CONFIG_FILE
from .Loader import ModuleLoader
from .mcp_integration import McpServer
from .middlewares import ApiAuthMiddleware, CollaborativeEditMiddleware, RoleMiddleware


class App:
    api: FastAPI

    def __init__(self):
        self.app_config = FastAPIAppConfig(APP_CONFIG_FILE)
        self.config = self.app_config.load()
        self._init_mcp_server()
        self.api = FastAPI(debug=Env.ENVIRONMENT == "development", lifespan=self._lifespan)
        self._init_api_middlewares()
        self._init_api_routes()

        AppRouter.set_openapi_schema(self.api)
        AuthSecurity.set_openapi_schema(self.api)
        AppRouter.set_app(self.api)
        AppRouter.create_schema_files(Env.SCHEMA_DIR)

        self.api.openapi = self._openapi_json

    def create(self):
        AppRouter.set_app(self.api)
        self.app_config.set_restarting(True)
        return self.api

    def _init_api_middlewares(self):
        origins = [Env.PUBLIC_UI_URL, "http://localhost:6274"]
        # FastAPI 0.141+ keeps included routers behind an internal wrapper.
        # Authorization filters are registered on the original API routes, so
        # middleware must inspect that stable route collection directly.
        self.api.add_middleware(RoleMiddleware, routes=AppRouter.api.routes)
        self.api.add_middleware(ApiAuthMiddleware, routes=AppRouter.api.routes)
        self.api.add_middleware(CollaborativeEditMiddleware)
        self.api.add_middleware(GZipMiddleware, minimum_size=1024, compresslevel=5)
        self.api.add_middleware(
            CORSMiddleware,
            allow_origins=origins,
            allow_credentials=True,
            allow_methods=["DELETE", "GET", "HEAD", "OPTIONS", "PATCH", "POST", "PUT"],
            allow_headers=[
                "Accept",
                "Referer",
                "Accept-Encoding",
                "Accept-Language",
                "Content-Encoding",
                "Content-Language",
                "Authorization",
                "Content-Type",
                "X-Requested-With",
                "User-Agent",
                "X-Forwarded-Proto",
                "X-Forwarded-Host",
                "x-custom-auth-headers",
                AuthSecurity.AUTHORIZATION_HEADER,
                AuthSecurity.REAL_IP_HEADER,
                AuthSecurity.FORWARDED_FOR_HEADER,
                AuthSecurity.API_TOKEN_HEADER,
                AuthSecurity.API_KEY_HEADER,
                AuthSecurity.MCP_TOOL_GROUP_UID_HEADER,
                "Mcp-Method",
                "Mcp-Name",
                "Mcp-Protocol-Version",
                "Mcp-Session-Id",
                "Last-Event-ID",
            ],
            expose_headers=["Mcp-Session-Id"],
        )

        middleware_modules = ModuleLoader.load(
            "middlewares", "Middleware", BaseMiddleware, not self.config.is_restarting
        )
        for module in middleware_modules.values():
            for middleware in module:
                if middleware.__auto_load__:
                    self.api.add_middleware(middleware)

    def _init_api_routes(self):
        self.api.router.route_class = AppExceptionHandlingRoute
        ModuleLoader.load("routes", "Api", log=not self.config.is_restarting)
        self.api.include_router(AppRouter.api)
        self.api.mount("/mcp", cast(Any, self.mcp_http_app))

    def _init_mcp_server(self):
        ModuleLoader.load("mcp_tools", "Mcp", log=not self.config.is_restarting)
        mcp_http_app, mcp_app = McpServer.get_http_app()
        self.mcp_http_app = mcp_http_app
        self.mcp_app = mcp_app

    def _openapi_json(self):
        with open(Env.SCHEMA_DIR / AppRouter.open_api_schema_file, "r") as f:
            content = f.read()
        return json_loads(content)

    @asynccontextmanager
    async def _lifespan(self, _: FastAPI):
        """Manage application lifespan events."""
        # Startup
        try:
            if not KeyVault.health_check():
                raise RuntimeError(
                    f"Vault provider '{KeyVault.name()}' is not accessible. "
                    f"Please check your configuration and credentials before starting the application."
                )
        except Exception:
            raise

        async with self.mcp_http_app.router.lifespan_context(self.mcp_http_app):
            yield
