from typing import Any, Optional
from pydantic import BaseModel
from uvicorn.config import LifespanType
from .Constants import DATA_DIR
from .core.utils.decorators import staticclass


class AppConfigModel(BaseModel):
    host: str
    port: int
    uds: Optional[str] = None
    lifespan: LifespanType
    ssl_options: dict[str, Any] = {}
    workers: int
    is_restarting: bool = False
    watch: bool = False
    enable_broker: bool = True


@staticclass
class AppConfig:
    CONFIG_FILE = DATA_DIR / "config.json"

    @staticmethod
    def create(
        host: str = "localhost",
        port: int = 5381,
        uds: Optional[str] = None,
        lifespan: LifespanType = "auto",
        ssl_options: Any = None,
        workers: int = 1,
        watch: bool = False,
        enable_broker: bool = True,
    ):
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        AppConfig.CONFIG_FILE.touch(exist_ok=True)

        config = AppConfigModel.model_validate(
            {
                "host": host,
                "port": port,
                "uds": uds,
                "lifespan": lifespan,
                "ssl_options": ssl_options or {},
                "workers": workers,
                "is_restarting": False,
                "watch": watch,
                "enable_broker": enable_broker,
            }
        )

        with open(AppConfig.CONFIG_FILE, "w") as f:
            f.write(config.model_dump_json())

    @staticmethod
    def load() -> AppConfigModel:
        if not AppConfig.CONFIG_FILE.exists():
            raise FileNotFoundError(f"Configuration file {AppConfig.CONFIG_FILE} does not exist.")

        with open(AppConfig.CONFIG_FILE, "r") as f:
            config = f.read()
            return AppConfigModel.model_validate_json(config)

    @staticmethod
    def set_restarting(is_restarting: bool):
        config = AppConfig.load()
        config.is_restarting = is_restarting

        with open(AppConfig.CONFIG_FILE, "w") as f:
            f.write(config.model_dump_json())
