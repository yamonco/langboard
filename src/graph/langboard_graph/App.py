from fastapi import FastAPI
from fastapi.middleware.gzip import GZipMiddleware
from langboard_shared.core.routing import AppExceptionHandlingRoute, AppRouter, BaseMiddleware
from langboard_shared.FastAPIAppConfig import FastAPIAppConfig
from .Constants import APP_CONFIG_FILE
from .core.graph.checkpoint import close_graph_checkpointer
from .Loader import ModuleLoader


class App:
    api: FastAPI

    def __init__(self):
        self.app_config = FastAPIAppConfig(APP_CONFIG_FILE)
        self.config = self.app_config.load()
        self.api = FastAPI(debug=True)
        self.api.add_event_handler("shutdown", close_graph_checkpointer)
        self._init_api_middlewares()
        self._init_api_routes()

        AppRouter.set_app(self.api)

    def create(self):
        AppRouter.set_app(self.api)
        try:
            self.app_config.set_restarting(True)
        except FileNotFoundError:
            self.app_config.create(
                host=self.config.host,
                port=self.config.port,
                uds=self.config.uds,
                lifespan=self.config.lifespan,
                ssl_options=self.config.ssl_options,
                workers=self.config.workers,
                timeout_keep_alive=self.config.timeout_keep_alive,
                healthcheck_interval=self.config.healthcheck_interval,
                watch=self.config.watch,
            )
            self.app_config.set_restarting(True)
        return self.api

    def _init_api_middlewares(self):
        self.api.add_middleware(GZipMiddleware, minimum_size=1024, compresslevel=5)

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
