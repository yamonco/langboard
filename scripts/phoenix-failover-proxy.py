"""Route new TCP connections to one of two Phoenix nodes during a browser probe."""

from __future__ import annotations
import argparse
import asyncio
from pathlib import Path


async def relay(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    try:
        while data := await reader.read(64 * 1024):
            writer.write(data)
            await writer.drain()
    except (ConnectionError, asyncio.IncompleteReadError):
        pass
    finally:
        writer.close()
        await writer.wait_closed()


class FailoverProxy:
    def __init__(self, mode_file: Path, targets: dict[str, tuple[str, int]]) -> None:
        self.mode_file = mode_file
        self.targets = targets

    def target(self) -> tuple[str, int]:
        mode = self.mode_file.read_text(encoding="ascii").strip()
        try:
            return self.targets[mode]
        except KeyError as error:
            raise RuntimeError(f"Unsupported Phoenix proxy mode: {mode!r}") from error

    async def handle(self, client_reader: asyncio.StreamReader, client_writer: asyncio.StreamWriter) -> None:
        try:
            target_host, target_port = self.target()
            target_reader, target_writer = await asyncio.open_connection(target_host, target_port)
        except (OSError, RuntimeError):
            client_writer.close()
            await client_writer.wait_closed()
            return

        upstream = asyncio.create_task(relay(client_reader, target_writer))
        downstream = asyncio.create_task(relay(target_reader, client_writer))
        _done, pending = await asyncio.wait(
            (upstream, downstream), return_when=asyncio.FIRST_COMPLETED
        )
        for task in pending:
            task.cancel()
        target_writer.close()
        client_writer.close()
        await asyncio.gather(upstream, downstream, return_exceptions=True)
        await target_writer.wait_closed()
        await client_writer.wait_closed()


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--mode-file", type=Path, required=True)
    parser.add_argument("--target-a", type=int, required=True)
    parser.add_argument("--target-b", type=int, required=True)
    args = parser.parse_args()

    proxy = FailoverProxy(
        args.mode_file,
        {"a": ("127.0.0.1", args.target_a), "b": ("127.0.0.1", args.target_b)},
    )
    server = await asyncio.start_server(proxy.handle, args.host, args.port)
    async with server:
        await server.serve_forever()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
