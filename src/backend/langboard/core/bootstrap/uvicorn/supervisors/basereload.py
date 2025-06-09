# Copyright (c) 2017-present, Encode OSS Ltd. All rights reserved.
#
# This file is derived from the original `supervisors/basereload.py` file in the Uvicorn project,
# available at: https://github.com/encode/uvicorn
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
import logging
import os
import signal
import sys
import threading
from collections.abc import Iterator
from pathlib import Path
from socket import socket
from types import FrameType
from typing import Callable
import click
from uvicorn.config import Config
from ....broadcast import DispatcherQueue
from .._subprocess import get_subprocess, run_broker


HANDLED_SIGNALS = (
    signal.SIGINT,  # Unix signal 2. Sent by Ctrl+C.
    signal.SIGTERM,  # Unix signal 15. Sent by `kill <pid>`.
)

logger = logging.getLogger("uvicorn.error")


class BaseReload:
    def __init__(
        self,
        config: Config,
        target: Callable[[list[socket] | None], None],
        sockets: list[socket],
    ) -> None:
        self.config = config
        self.target = target
        self.sockets = sockets
        self.should_exit = threading.Event()
        self.pid = os.getpid()
        self.is_restarting = False
        self.reloader_name: str | None = None

        DispatcherQueue.start()

    def signal_handler(self, sig: int, frame: FrameType | None) -> None:  # pragma: full coverage
        """
        A signal handler that is registered with the parent process.
        """
        if sys.platform == "win32" and self.is_restarting:
            self.is_restarting = False
        else:
            self.should_exit.set()

    def run(self) -> None:
        self.startup()
        for changes in self:
            if changes:
                logger.info("File changed. Restarting the server..")
                self.restart()

        self.shutdown()

    def pause(self) -> None:
        if self.should_exit.wait(self.config.reload_delay):
            raise StopIteration()

    def __iter__(self) -> Iterator[list[Path] | None]:
        return self

    def __next__(self) -> list[Path] | None:
        return self.should_restart()

    def startup(self) -> None:
        message = f"Started reloader process [{self.pid}] using {self.reloader_name}"
        color_message = "Started reloader process [{}] using {}".format(
            click.style(str(self.pid), fg="cyan", bold=True),
            click.style(str(self.reloader_name), fg="cyan", bold=True),
        )
        logger.info(message, extra={"color_message": color_message})

        for sig in HANDLED_SIGNALS:
            signal.signal(sig, self.signal_handler)

        if getattr(self.config, "enable_broker", True):
            self.broker_process = run_broker(is_restarting=False)
        else:
            self.broker_process = None

        self.process = get_subprocess(
            config=self.config,
            target=self.target,
            sockets=self.sockets,
        )
        self.process.start()

    def restart(self) -> None:
        if self.broker_process:
            if self.broker_process.pid:
                os.kill(self.broker_process.pid, signal.SIGTERM)
            else:
                self.broker_process.terminate()
                self.broker_process.kill()
            self.broker_process.join()

        if sys.platform == "win32":  # pragma: py-not-win32
            self.is_restarting = True
            assert self.process.pid is not None
            os.kill(self.process.pid, signal.CTRL_C_EVENT)

            # This is a workaround to ensure the Ctrl+C event is processed
            sys.stdout.write(" ")  # This has to be a non-empty string
            sys.stdout.flush()
        else:  # pragma: py-win32
            self.process.terminate()
        self.process.join()

        if getattr(self.config, "enable_broker", True):
            self.broker_process = run_broker(is_restarting=True)
        else:
            self.broker_process = None

        self.process = get_subprocess(
            config=self.config,
            target=self.target,
            sockets=self.sockets,
        )
        self.process.start()

    def shutdown(self) -> None:
        if self.broker_process:
            if self.broker_process.pid:
                os.kill(self.broker_process.pid, signal.SIGTERM)
            else:
                self.broker_process.terminate()
                self.broker_process.kill()
            self.broker_process.join()

        if sys.platform == "win32":
            self.should_exit.set()  # pragma: py-not-win32
        else:
            self.process.terminate()  # pragma: py-win32
        self.process.join()

        for sock in self.sockets:
            sock.close()

        DispatcherQueue.close()

        message = f"Stopping reloader process [{str(self.pid)}]"
        color_message = "Stopping reloader process [{}]".format(click.style(str(self.pid), fg="cyan", bold=True))
        logger.info(message, extra={"color_message": color_message})

    def should_restart(self) -> list[Path] | None:
        raise NotImplementedError("Reload strategies should override should_restart()")
