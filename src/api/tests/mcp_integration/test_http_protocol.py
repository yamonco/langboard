"""Exercise legacy and modern clients over real stateless HTTP transport."""

import asyncio
import socket
from types import SimpleNamespace
import pytest
import uvicorn
from fastmcp import Client
from langboard.mcp_integration.Server import _create_fastmcp
from langboard.middlewares.McpAuthMiddleware import mcp_auth_context


class FixtureGroupMiddleware:
    """Provide an isolated group fixture; this is not production authentication proof."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        token = mcp_auth_context.set({"tool_group": SimpleNamespace(activated_at=object(), tools=["record"])})
        try:
            await self.app(scope, receive, send)
        finally:
            mcp_auth_context.reset(token)


@pytest.mark.parametrize("mode", ["legacy", "2026-07-28"])
async def test_stateless_http_negotiation_discovery_and_write(mode):
    existing_tasks = asyncio.all_tasks()
    server = _create_fastmcp()
    writes = []

    @server.tool
    def record(value: int) -> dict[str, int]:
        writes.append(value)
        return {"value": value}

    @server.resource("fixture://example")
    def example() -> str:
        return "Example resource"

    @server.prompt
    def example_prompt() -> str:
        return "Example prompt"

    app = server.http_app(path="/stream", stateless_http=True, allowed_hosts=["127.0.0.1:*", "127.0.0.1"])
    app.add_middleware(FixtureGroupMiddleware)
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    port = listener.getsockname()[1]
    http_server = uvicorn.Server(uvicorn.Config(app, log_level="critical", lifespan="on"))
    task = asyncio.create_task(http_server.serve(sockets=[listener]))
    try:
        for _ in range(500):
            if http_server.started or task.done():
                break
            await asyncio.sleep(0.01)
        assert http_server.started
        async with Client(f"http://127.0.0.1:{port}/stream", mode=mode) as client:
            assert client.protocol_version == ("2025-11-25" if mode == "legacy" else mode)
            assert [tool.name for tool in await client.list_tools()] == ["record"]
            assert [str(resource.uri) for resource in await client.list_resources()] == ["fixture://example"]
            assert [prompt.name for prompt in await client.list_prompts()] == ["example_prompt"]
            result = await client.call_tool("record", {"value": 7})
            assert result.structured_content == {"value": 7}
            assert writes == [7]
        # A new client connection also works without an old session header.
        async with Client(f"http://127.0.0.1:{port}/stream", mode=mode) as client:
            assert [tool.name for tool in await client.list_tools()] == ["record"]
    finally:
        http_server.should_exit = True
        await asyncio.wait_for(task, timeout=5)
        listener.close()
        # sse-starlette's loop-local shutdown watcher can outlive uvicorn.
        watchers = [
            pending
            for pending in asyncio.all_tasks() - existing_tasks
            if getattr(pending.get_coro(), "__name__", "") == "_shutdown_watcher"
        ]
        for pending in watchers:
            pending.cancel()
        await asyncio.gather(*watchers, return_exceptions=True)
