from typing import Any
from fastapi import status
from langboard_shared.core.routing import ApiErrorCode, BaseMiddleware, JsonResponse
from langboard_shared.domain.models import McpToolGroup
from starlette.types import Message, Receive, Send
from langboard.middlewares.McpAuthMiddleware import mcp_auth_context
from langboard.middlewares.ToolListFiltering import (
    BodyLimitExceeded,
    BoundedBodyBuffer,
    UnsafeToolListPayload,
    filter_tools_list_response,
    is_tools_list_request,
)


_MAX_REQUEST_BODY_BYTES = 4 * 1024 * 1024
_MAX_TOOL_LIST_RESPONSE_BYTES = 4 * 1024 * 1024


class DynamicSseMiddleware(BaseMiddleware):
    """
    Dynamic SSE middleware that filters tools based on tool group.
    Expects authentication to be handled by McpAuthMiddleware before this middleware.
    """

    __auto_load__ = False

    async def __call__(self, scope: dict[str, Any], receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        auth_data = mcp_auth_context.get()

        if not auth_data or "tool_group" not in auth_data:
            response = JsonResponse(ApiErrorCode.PE1001, status_code=status.HTTP_403_FORBIDDEN)
            await response(scope, receive, send)
            return

        tool_group: McpToolGroup = auth_data["tool_group"]

        try:
            request_messages, request_body = await _buffer_request(receive)
        except BodyLimitExceeded:
            response = JsonResponse(
                content={"error": "MCP request body exceeds the safe filtering limit"},
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            )
            await response(scope, receive, send)
            return

        replay_receive = _ReplayReceive(request_messages, receive)
        if not is_tools_list_request(request_body):
            await self.app(scope, replay_receive, send)
            return

        response_collector = _BoundedResponseCollector()
        try:
            await self.app(scope, replay_receive, response_collector.send)
            await response_collector.forward_filtered(send, tool_group.tools)
        except (BodyLimitExceeded, UnsafeToolListPayload):
            response = JsonResponse(
                content={"error": "Unable to safely filter the MCP tools/list response"},
                status_code=status.HTTP_502_BAD_GATEWAY,
            )
            await response(scope, receive, send)


async def _buffer_request(receive: Receive) -> tuple[list[Message], bytes]:
    messages: list[Message] = []
    body = BoundedBodyBuffer(_MAX_REQUEST_BODY_BYTES)

    while True:
        message = await receive()
        messages.append(message)

        if message["type"] == "http.disconnect":
            break
        if message["type"] != "http.request":
            continue

        body.append(message.get("body", b""))
        if not message.get("more_body", False):
            break

    return messages, body.getvalue()


class _ReplayReceive:
    def __init__(self, messages: list[Message], receive: Receive) -> None:
        self._messages = iter(messages)
        self._receive = receive

    async def __call__(self) -> Message:
        try:
            return next(self._messages)
        except StopIteration:
            return await self._receive()


class _BoundedResponseCollector:
    def __init__(self) -> None:
        self._start: Message | None = None
        self._body = BoundedBodyBuffer(_MAX_TOOL_LIST_RESPONSE_BYTES)
        self._body_complete = False
        self._tail: list[Message] = []

    async def send(self, message: Message) -> None:
        if message["type"] == "http.response.start":
            self._start = message
            return
        if message["type"] == "http.response.body":
            self._body.append(message.get("body", b""))
            if not message.get("more_body", False):
                self._body_complete = True
            return
        self._tail.append(message)

    async def forward_filtered(self, send: Send, allowed_tools: list[str]) -> None:
        if self._start is None:
            raise UnsafeToolListPayload("MCP tools/list response did not start")
        if not self._body_complete:
            raise UnsafeToolListPayload("MCP tools/list response did not complete")

        content_type = _get_header(self._start, b"content-type").decode("latin-1")
        filtered_body = filter_tools_list_response(self._body.getvalue(), content_type, allowed_tools)

        start = {**self._start, "headers": _replace_content_length(self._start, len(filtered_body))}
        await send(start)
        await send({"type": "http.response.body", "body": filtered_body, "more_body": False})
        for message in self._tail:
            await send(message)


def _get_header(message: Message, name: bytes) -> bytes:
    for header_name, header_value in message.get("headers", []):
        if header_name.lower() == name:
            return header_value
    return b""


def _replace_content_length(message: Message, body_length: int) -> list[tuple[bytes, bytes]]:
    headers = [
        (name, value) for name, value in message.get("headers", []) if name.lower() != b"content-length"
    ]
    headers.append((b"content-length", str(body_length).encode("ascii")))
    return headers
