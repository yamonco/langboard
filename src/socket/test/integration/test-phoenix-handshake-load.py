"""Probe authenticated Phoenix WebSocket handshakes without exposing credentials."""

import argparse
import asyncio
import json
import sys
from collections import Counter
from time import monotonic
from typing import cast
from urllib.parse import quote
import websockets


async def connect_once(url: str, token: str, semaphore: asyncio.Semaphore) -> tuple[str, float]:
    async with semaphore:
        started = monotonic()
        try:
            async with websockets.connect(
                f"{url}?authorization={quote(token, safe='')}",
                open_timeout=10,
            ) as connection:
                for _ in range(2):
                    frame = cast(object, json.loads(await asyncio.wait_for(connection.recv(), 5)))
                    if not isinstance(frame, dict) or cast(dict[str, object], frame).get("event") != "subscribed":
                        return "unexpected_bootstrap", monotonic() - started
                return "ok", monotonic() - started
        except Exception as error:
            response = getattr(error, "response", None)
            status = getattr(response, "status_code", None)
            return f"http_{status}" if isinstance(status, int) else type(error).__name__, monotonic() - started


async def probe(url: str, token: str, concurrency: int, total: int) -> None:
    semaphore = asyncio.Semaphore(concurrency)
    results = await asyncio.gather(*(connect_once(url, token, semaphore) for _ in range(total)))
    counts = Counter(status for status, _duration in results)
    longest = max(duration for _status, duration in results)
    print(f"handshakes={total} concurrency={concurrency} results={dict(counts)} max_seconds={longest:.3f}")
    if counts != {"ok": total}:
        raise SystemExit(1)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    _ = parser.add_argument("--url", required=True, help="WebSocket URL without an authorization query")
    _ = parser.add_argument("--concurrency", type=int, default=30)
    _ = parser.add_argument("--total", type=int, default=120)
    args = parser.parse_args()
    url = cast(object, args.url)
    concurrency = cast(object, args.concurrency)
    total = cast(object, args.total)
    if (
        not isinstance(url, str)
        or not isinstance(concurrency, int)
        or not isinstance(total, int)
        or concurrency < 1
        or total < 1
        or not url.startswith(("ws://", "wss://"))
        or "?" in url
    ):
        parser.error("Use positive counts and a WebSocket URL without query parameters")
    token = sys.stdin.readline().strip()
    if not token:
        parser.error("An access token is required on standard input")
    asyncio.run(probe(url, token, concurrency, total))


if __name__ == "__main__":
    main()
