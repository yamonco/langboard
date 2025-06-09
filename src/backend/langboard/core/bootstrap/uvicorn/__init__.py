# Copyright (c) 2017-present, Encode OSS Ltd. All rights reserved.
#
# This file is based on `main.py` from the Uvicorn project:
# https://github.com/encode/uvicorn/blob/master/uvicorn/main.py
#
# The original file was renamed to `__init__.py` and modified
# to support a customized server initialization with multiprocessing.Queue integration.
#
# Licensed under the BSD 3-Clause License. Redistribution and use in source and binary
# forms, with or without modification, are permitted provided that the following
# conditions are met:
#
# 1. Redistributions of source code must retain the above copyright notice, this list
#    of conditions and the following disclaimer.
# 2. Redistributions in binary form must reproduce the above copyright notice, this list
#    of conditions and the following disclaimer in the documentation and/or other
#    materials provided with the distribution.
# 3. Neither the name of the copyright holder nor the names of its contributors
#    may be used to endorse or promote products derived from this software without
#    specific prior written permission.
#
# THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS" AND
# ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE IMPLIED
# WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE DISCLAIMED.
# IN NO EVENT SHALL THE COPYRIGHT HOLDER OR CONTRIBUTORS BE LIABLE FOR ANY DIRECT,
# INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING, BUT
# NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES; LOSS OF USE, DATA, OR
# PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY OF LIABILITY,
# WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE)
# ARISING IN ANY WAY OUT OF THE USE OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY
# OF SUCH DAMAGE.
#
# ---
# Modified by [Yamon], 2025
# Purpose: Custom server runner using multiprocessing.Queue support and change logging.


from __future__ import annotations
import asyncio
import logging
import os
import socket
import ssl
import sys
from configparser import RawConfigParser
from typing import IO, Any, Callable
import click
from uvicorn._types import ASGIApplication
from uvicorn.config import (
    LOGGING_CONFIG,
    SSL_PROTOCOL_VERSION,
    Config,
    HTTPProtocolType,
    InterfaceType,
    LifespanType,
    LoopSetupType,
    WSProtocolType,
)
from .server import Server
from .supervisors import ChangeReload, Multiprocess


STARTUP_FAILURE = 3

logger = logging.getLogger("uvicorn.error")


def create_config(
    app: ASGIApplication | Callable[..., Any] | str,
    *,
    host: str = "127.0.0.1",
    port: int = 8000,
    uds: str | None = None,
    fd: int | None = None,
    loop: LoopSetupType = "auto",
    http: type[asyncio.Protocol] | HTTPProtocolType = "auto",
    ws: type[asyncio.Protocol] | WSProtocolType = "auto",
    ws_max_size: int = 16777216,
    ws_max_queue: int = 32,
    ws_ping_interval: float | None = 20.0,
    ws_ping_timeout: float | None = 20.0,
    ws_per_message_deflate: bool = True,
    lifespan: LifespanType = "auto",
    interface: InterfaceType = "auto",
    reload: bool = False,
    reload_dirs: list[str] | str | None = None,
    reload_includes: list[str] | str | None = None,
    reload_excludes: list[str] | str | None = None,
    reload_delay: float = 0.25,
    workers: int | None = None,
    env_file: str | os.PathLike[str] | None = None,
    log_config: dict[str, Any] | str | RawConfigParser | IO[Any] | None = LOGGING_CONFIG,
    log_level: str | int | None = None,
    access_log: bool = True,
    proxy_headers: bool = True,
    server_header: bool = True,
    date_header: bool = True,
    forwarded_allow_ips: list[str] | str | None = None,
    root_path: str = "",
    limit_concurrency: int | None = None,
    backlog: int = 2048,
    limit_max_requests: int | None = None,
    timeout_keep_alive: int = 5,
    timeout_graceful_shutdown: int | None = None,
    ssl_keyfile: str | os.PathLike[str] | None = None,
    ssl_certfile: str | os.PathLike[str] | None = None,
    ssl_keyfile_password: str | None = None,
    ssl_version: int = SSL_PROTOCOL_VERSION,
    ssl_cert_reqs: int = ssl.CERT_NONE,
    ssl_ca_certs: str | None = None,
    ssl_ciphers: str = "TLSv1",
    headers: list[tuple[str, str]] | None = None,
    use_colors: bool | None = None,
    app_dir: str | None = None,
    factory: bool = False,
    h11_max_incomplete_event_size: int | None = None,
    enable_broker: bool = True,
) -> Config:
    if app_dir is not None:
        sys.path.insert(0, app_dir)

    def bind_socket(self) -> socket.socket:
        logger_args: list[str | int]
        if self.uds:  # pragma: py-win32
            path = self.uds
            sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)  # type: ignore
            try:
                sock.bind(path)
                uds_perms = 0o666
                os.chmod(self.uds, uds_perms)
            except OSError as exc:  # pragma: full coverage
                logger.error(exc)
                sys.exit(1)

            message = "Running on unix socket %s (Press CTRL+C to quit)"
            sock_name_format = "%s"
            color_message = "Running on " + click.style(sock_name_format, bold=True) + " (Press CTRL+C to quit)"
            logger_args = [self.uds]
        elif self.fd:  # pragma: py-win32
            sock = socket.fromfd(self.fd, socket.AF_UNIX, socket.SOCK_STREAM)  # type: ignore
            message = "Running on socket %s (Press CTRL+C to quit)"
            fd_name_format = "%s"
            color_message = "Running on " + click.style(fd_name_format, bold=True) + " (Press CTRL+C to quit)"
            logger_args = [sock.getsockname()]
        else:
            family = socket.AF_INET
            addr_format = "%s://%s:%d"

            if self.host and ":" in self.host:  # pragma: full coverage
                # It's an IPv6 address.
                family = socket.AF_INET6
                addr_format = "%s://[%s]:%d"

            sock = socket.socket(family=family)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                sock.bind((self.host, self.port))
            except OSError as exc:  # pragma: full coverage
                logger.error(exc)
                sys.exit(1)

            message = f"Running on {addr_format} (Press CTRL+C to quit)"
            color_message = "Running on " + click.style(addr_format, bold=True) + " (Press CTRL+C to quit)"
            protocol_name = "https" if self.is_ssl else "http"
            logger_args = [protocol_name, self.host, sock.getsockname()[1]]
        logger.info(message, *logger_args, extra={"color_message": color_message})
        sock.set_inheritable(True)
        return sock

    Config.bind_socket = bind_socket

    config = Config(
        app,
        host=host,
        port=port,
        uds=uds,
        fd=fd,
        loop=loop,
        http=http,
        ws=ws,
        ws_max_size=ws_max_size,
        ws_max_queue=ws_max_queue,
        ws_ping_interval=ws_ping_interval,
        ws_ping_timeout=ws_ping_timeout,
        ws_per_message_deflate=ws_per_message_deflate,
        lifespan=lifespan,
        interface=interface,
        reload=reload,
        reload_dirs=reload_dirs,
        reload_includes=reload_includes,
        reload_excludes=reload_excludes,
        reload_delay=reload_delay,
        workers=workers,
        env_file=env_file,
        log_config=log_config,
        log_level=log_level,
        access_log=access_log,
        proxy_headers=proxy_headers,
        server_header=server_header,
        date_header=date_header,
        forwarded_allow_ips=forwarded_allow_ips,
        root_path=root_path,
        limit_concurrency=limit_concurrency,
        backlog=backlog,
        limit_max_requests=limit_max_requests,
        timeout_keep_alive=timeout_keep_alive,
        timeout_graceful_shutdown=timeout_graceful_shutdown,
        ssl_keyfile=ssl_keyfile,
        ssl_certfile=ssl_certfile,
        ssl_keyfile_password=ssl_keyfile_password,
        ssl_version=ssl_version,
        ssl_cert_reqs=ssl_cert_reqs,
        ssl_ca_certs=ssl_ca_certs,
        ssl_ciphers=ssl_ciphers,
        headers=headers,
        use_colors=use_colors,
        factory=factory,
        h11_max_incomplete_event_size=h11_max_incomplete_event_size,
    )

    config.enable_broker = enable_broker
    return config


def run(config: Config) -> None:
    server = Server(config=config)

    try:
        if config.should_reload:
            sock = config.bind_socket()
            ChangeReload(config, target=server.run, sockets=[sock]).run()
        else:
            sock = config.bind_socket()
            Multiprocess(config, target=server.run, sockets=[sock]).run()
    except KeyboardInterrupt:
        pass  # pragma: full coverage
    except Exception as exc:
        logger.error("Error starting server: %s", exc, exc_info=True)
        sys.exit(STARTUP_FAILURE)
    finally:
        if config.uds and os.path.exists(config.uds):
            os.remove(config.uds)  # pragma: py-win32

    if not server.started and not config.should_reload and config.workers == 1:
        sys.exit(STARTUP_FAILURE)
