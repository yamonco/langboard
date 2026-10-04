from logging import CRITICAL, ERROR, NOTSET, Handler, basicConfig, getLevelNamesMapping, getLogger, setLoggerClass
from logging import Logger as LoggingLogger
from typing import Any
from rich.logging import RichHandler
from sentry_sdk import init as sentry_init
from ...Env import Env
from ..utils.decorators import class_instance, thread_safe_singleton
from .LogFileHandler import LogFileHandler


class _LoggerWrapper(LoggingLogger):
    def __init__(self, name, level=NOTSET):
        if not name.startswith(Env.PROJECT_NAME) and not name.startswith("sqlalchemy"):
            level = ERROR
        super().__init__(name, level)


setLoggerClass(_LoggerWrapper)


@class_instance()
@thread_safe_singleton
class Logger:
    """Manages the application's logging."""

    main: LoggingLogger

    @property
    def terminal_level(self) -> int:
        levels = getLevelNamesMapping()
        return (
            levels[Env.TERMINAL_LOGGING_LEVEL]
            if Env.TERMINAL_LOGGING_LEVEL in levels
            else (levels["INFO"] if Env.ENVIRONMENT == "production" else levels["INFO"])
        )

    @property
    def file_level(self) -> int:
        levels = getLevelNamesMapping()
        return (
            levels[Env.FILE_LOGGING_LEVEL]
            if Env.FILE_LOGGING_LEVEL in levels
            else (levels["ERROR"] if Env.ENVIRONMENT == "production" else levels["WARNING"])
        )

    def __init__(self):
        basicConfig(
            level=self.terminal_level,
            format="%(name)s: %(message)s",
            datefmt="[%Y-%m-%d %X]",
            handlers=self.get_handlers(),
        )

        self.main = getLogger(Env.PROJECT_NAME)

        getLogger("asyncio").setLevel(ERROR)
        getLogger("multipart").setLevel(ERROR)
        getLogger("python_multipart.multipart").setLevel(ERROR)
        getLogger("aiosqlite").setLevel(ERROR)
        getLogger("asyncpg").setLevel(ERROR)
        getLogger("httpx").setLevel(ERROR)
        getLogger("urllib3.connectionpool").setLevel(ERROR)
        getLogger("httpcore.connection").setLevel(ERROR)
        getLogger("httpcore.http11").setLevel(ERROR)
        getLogger("strawberry.execution").setLevel(CRITICAL)

        if Env.SENTRY_DSN:
            sentry_init(
                dsn=Env.SENTRY_DSN,
                environment=Env.ENVIRONMENT if Env.ENVIRONMENT == "production" else "development",
            )

    def get_config(self) -> dict[str, Any]:
        return {
            "version": 1,
            "disable_existing_loggers": False,
            "formatters": {
                "mcp_telemetry": {"format": "%(message)s"},
                "default": {
                    "()": "uvicorn.logging.DefaultFormatter",
                    "fmt": f"{Env.PROJECT_NAME}: %(message)s",
                    "datefmt": "[%Y-%m-%d %X]",
                    "use_colors": False,
                },
                "access": {
                    "()": "uvicorn.logging.AccessFormatter",
                    "fmt": f'{Env.PROJECT_NAME}: %(client_addr)s - "%(request_line)s" %(status_code)s',  # noqa: E501
                    "datefmt": "[%Y-%m-%d %X]",
                    "use_colors": False,
                },
            },
            "handlers": {
                "mcp_telemetry": {
                    "class": "logging.StreamHandler",
                    "formatter": "mcp_telemetry",
                    "level": "INFO",
                    "stream": "ext://sys.stdout",
                },
                "default": {
                    "formatter": "default",
                    "class": "rich.logging.RichHandler",
                    "level": self.terminal_level,
                    "omit_repeated_times": False,
                    "markup": True,
                    "rich_tracebacks": True,
                    "tracebacks_show_locals": True,
                },
                "access": {
                    "formatter": "access",
                    "class": "rich.logging.RichHandler",
                    "level": self.terminal_level,
                    "omit_repeated_times": False,
                    "markup": True,
                    "rich_tracebacks": True,
                    "tracebacks_show_locals": True,
                },
                "file": {
                    "class": "langboard_shared.core.logger.LogFileHandler.LogFileHandler",
                    "level": self.file_level,
                    "log_dir": str(Env.LOGGING_DIR),
                },
                "executable_file": {
                    "class": "langboard_shared.core.logger.LogFileHandler.LogFileHandler",
                    "level": self.file_level,
                    "log_dir": str(Env.LOGGING_DIR),
                    "is_terminal": True,
                },
            },
            "loggers": {
                f"{Env.PROJECT_NAME}.mcp.telemetry": {
                    "handlers": ["mcp_telemetry"],
                    "level": "INFO",
                    "propagate": False,
                },
                "uvicorn": {"handlers": ["default", "file"], "level": self.terminal_level, "propagate": False},
                "uvicorn.error": {"handlers": ["default", "file"], "level": self.terminal_level, "propagate": False},
                "uvicorn.access": {"handlers": ["access", "file"], "level": self.terminal_level, "propagate": False},
            },
        }

    @staticmethod
    def use(name: str) -> LoggingLogger:
        """Returns a logger with the given name."""
        return getLogger(f"{Env.PROJECT_NAME}.{name}")

    def get_handlers(self) -> list[Handler]:
        handlers = [
            RichHandler(
                level=self.terminal_level,
                omit_repeated_times=False,
                markup=True,
                rich_tracebacks=True,
                tracebacks_show_locals=True,
            ),
            LogFileHandler(level=self.file_level, log_dir=Env.LOGGING_DIR, is_terminal=Env.IS_EXECUTABLE),
        ]

        return handlers
