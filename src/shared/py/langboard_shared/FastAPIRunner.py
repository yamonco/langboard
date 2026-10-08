from os.path import dirname
from pathlib import Path
from ssl import CERT_NONE
from uvicorn.config import SSL_PROTOCOL_VERSION
from .core.bootstrap.uvicorn import create_config
from .core.bootstrap.uvicorn import run as run_server
from .core.logger import Logger
from .FastAPIAppConfig import FastAPIAppConfig


def run(app: str, config_file: str | Path, watch_dir: str | Path):
    config = FastAPIAppConfig(config_file).load()

    try:
        uvicorn_config = create_config(
            app,
            host=config.host,
            port=config.port,
            uds=config.uds,
            lifespan=config.lifespan,
            ws="none",
            ssl_keyfile=config.ssl_options.get("keyfile"),
            ssl_certfile=config.ssl_options.get("certfile"),
            ssl_keyfile_password=config.ssl_options.get("keyfile_password"),
            ssl_version=config.ssl_options.get("version", SSL_PROTOCOL_VERSION),
            ssl_cert_reqs=config.ssl_options.get("cert_reqs", CERT_NONE),
            ssl_ca_certs=config.ssl_options.get("ca_certs"),
            workers=config.workers,
            timeout_worker_healthcheck=config.healthcheck_interval,
            reload=config.watch,
            reload_dirs=([str(watch_dir), dirname(__file__)] if config.watch else None),
            log_config=Logger.get_config(),
            app_dir=str(watch_dir),
        )

        run_server(uvicorn_config)
    except Exception:
        return
