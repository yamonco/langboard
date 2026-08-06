import asyncio
import json
import sys
from contextvars import ContextVar
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Any
import pytest


_SUBJECT = Path(__file__).parents[2] / "langboard" / "middlewares" / "ToolListFiltering.py"
_SPEC = spec_from_file_location("langboard_tool_list_filtering_contract", _SUBJECT)
assert _SPEC is not None and _SPEC.loader is not None
_MODULE = module_from_spec(_SPEC)
_SPEC.loader.exec_module(_MODULE)

BodyLimitExceeded = _MODULE.BodyLimitExceeded
BoundedBodyBuffer = _MODULE.BoundedBodyBuffer
UnsafeToolListPayload = _MODULE.UnsafeToolListPayload
filter_tools_list_response = _MODULE.filter_tools_list_response
is_tools_list_request = _MODULE.is_tools_list_request


def test_multichunk_request_is_detected_after_bounded_buffering() -> None:
    """A tools/list method split between transport chunks remains detectable."""

    buffer = BoundedBodyBuffer(128)
    buffer.append(b'{"jsonrpc":"2.0","method":"tools')
    buffer.append(b'/list","id":1}')

    assert is_tools_list_request(buffer.getvalue()) is True


def test_bounded_buffer_rejects_chunk_that_crosses_limit() -> None:
    """The buffer rejects an oversized final chunk before retaining it."""

    buffer = BoundedBodyBuffer(5)
    buffer.append(b"1234")

    with pytest.raises(BodyLimitExceeded):
        buffer.append(b"56")

    assert buffer.getvalue() == b"1234"


def test_json_response_filters_to_empty_for_empty_group() -> None:
    """An empty tool group must receive an empty list instead of every tool."""

    response = b'{"jsonrpc":"2.0","id":1,"result":{"tools":[{"name":"secret"}]}}'

    filtered = filter_tools_list_response(response, "application/json", [])

    assert json.loads(filtered)["result"]["tools"] == []


def test_multichunk_sse_response_filters_complete_buffer() -> None:
    """A JSON-RPC SSE event split across chunks is filtered after reassembly."""

    chunks = [
        b'event: message\r\ndata: {"jsonrpc":"2.0","id":1,"result":{"tools":[',
        b'{"name":"allowed"},{"name":"secret"}]}}\r\n\r\n',
    ]

    filtered = filter_tools_list_response(b"".join(chunks), "text/event-stream; charset=utf-8", ["allowed"])
    data_line = next(line for line in filtered.decode("utf-8").splitlines() if line.startswith("data:"))
    payload = json.loads(data_line.removeprefix("data:").strip())

    assert [tool["name"] for tool in payload["result"]["tools"]] == ["allowed"]


def test_malformed_success_response_fails_closed() -> None:
    """An unexpected successful payload cannot bypass the allowlist filter."""

    response = b'{"jsonrpc":"2.0","id":1,"result":{"unexpected":true}}'

    with pytest.raises(UnsafeToolListPayload):
        filter_tools_list_response(response, "application/json", ["allowed"])


def test_json_rpc_error_is_safe_to_forward() -> None:
    """A JSON-RPC error contains no tool inventory and remains intact."""

    response = b'{"jsonrpc":"2.0","id":1,"error":{"code":-32600,"message":"bad request"}}'

    filtered = filter_tools_list_response(response, "application/json", [])

    assert json.loads(filtered) == json.loads(response)


def test_batch_request_and_response_filter_every_tool_inventory() -> None:
    """A tools/list call cannot bypass filtering by appearing inside a JSON-RPC batch."""

    request = b'[{"jsonrpc":"2.0","method":"ping","id":1},{"jsonrpc":"2.0","method":"tools/list","id":2}]'
    response = b'[{"jsonrpc":"2.0","id":1,"result":{}},{"jsonrpc":"2.0","id":2,"result":{"tools":[{"name":"secret"}]}}]'

    assert is_tools_list_request(request) is True
    filtered = filter_tools_list_response(response, "application/json", [])
    assert json.loads(filtered)[1]["result"]["tools"] == []


def test_batch_response_without_tools_result_or_error_fails_closed() -> None:
    """A batch detected as tools/list cannot return only unrelated successful results."""

    response = b'[{"jsonrpc":"2.0","id":1,"result":{}}]'

    with pytest.raises(UnsafeToolListPayload):
        filter_tools_list_response(response, "application/json", ["allowed"])


def test_batch_tools_list_error_is_safe_without_inventory() -> None:
    """A batch-level tools/list error is forwardable because it contains no inventory."""

    response = (
        b'[{"jsonrpc":"2.0","id":1,"result":{}},{"jsonrpc":"2.0","id":2,"error":{"code":-32603,"message":"failed"}}]'
    )

    filtered = filter_tools_list_response(response, "application/json", [])

    assert json.loads(filtered) == json.loads(response)


def test_asgi_filter_handles_split_request_and_sse_response(monkeypatch: pytest.MonkeyPatch) -> None:
    """The middleware buffers both ASGI directions and never leaks an empty group's tools."""

    dynamic_module, auth_context = _load_dynamic_middleware(monkeypatch)
    auth_context.set({"tool_group": SimpleNamespace(tools=[])})
    secret_response = b'event: message\r\ndata: {"jsonrpc":"2.0","id":1,"result":{"tools":[{"name":"secret"}]}}\r\n\r\n'
    request_messages = [
        {"type": "http.request", "body": b'{"jsonrpc":"2.0","method":"tools/', "more_body": True},
        {"type": "http.request", "body": b'list","id":1}', "more_body": False},
    ]
    sent: list[dict[str, Any]] = []

    async def app(scope: dict[str, Any], receive: Any, send: Any) -> None:
        assert (await receive())["more_body"] is True
        assert (await receive())["more_body"] is False
        await send(
            {
                "type": "http.response.start",
                "status": 200,
                "headers": [(b"content-type", b"text/event-stream"), (b"content-length", b"999")],
            }
        )
        midpoint = len(secret_response) // 2
        await send({"type": "http.response.body", "body": secret_response[:midpoint], "more_body": True})
        await send({"type": "http.response.body", "body": secret_response[midpoint:], "more_body": False})

    async def receive() -> dict[str, Any]:
        return request_messages.pop(0)

    async def send(message: dict[str, Any]) -> None:
        sent.append(message)

    asyncio.run(dynamic_module.DynamicSseMiddleware(app)({"type": "http"}, receive, send))

    response_body = sent[1]["body"]
    assert b'"tools":[]' in response_body
    assert b"secret" not in response_body
    assert dict(sent[0]["headers"])[b"content-length"] == str(len(response_body)).encode("ascii")


def test_asgi_filter_replaces_oversized_response(monkeypatch: pytest.MonkeyPatch) -> None:
    """An oversized tools/list response becomes a bounded 502 without forwarding its bytes."""

    dynamic_module, auth_context = _load_dynamic_middleware(monkeypatch)
    auth_context.set({"tool_group": SimpleNamespace(tools=["allowed"])})
    request_messages = [
        {"type": "http.request", "body": b'{"jsonrpc":"2.0","method":"tools/list","id":1}', "more_body": False}
    ]
    sent: list[dict[str, Any]] = []

    async def app(scope: dict[str, Any], receive: Any, send: Any) -> None:
        await receive()
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send(
            {
                "type": "http.response.body",
                "body": b"secret" * (dynamic_module._MAX_TOOL_LIST_RESPONSE_BYTES // 6 + 1),
                "more_body": False,
            }
        )

    async def receive() -> dict[str, Any]:
        return request_messages.pop(0)

    async def send(message: dict[str, Any]) -> None:
        sent.append(message)

    asyncio.run(dynamic_module.DynamicSseMiddleware(app)({"type": "http"}, receive, send))

    assert sent[0]["status"] == 502
    assert b"secret" not in sent[1]["body"]


def test_asgi_filter_rejects_oversized_request_before_downstream(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An oversized request is rejected before the MCP application can process it."""

    dynamic_module, auth_context = _load_dynamic_middleware(monkeypatch)
    dynamic_module._MAX_REQUEST_BODY_BYTES = 48
    auth_context.set({"tool_group": SimpleNamespace(tools=[])})
    request_messages = [
        {"type": "http.request", "body": b'{"jsonrpc":"2.0","method":"tools/list",', "more_body": True},
        {"type": "http.request", "body": b'"padding":"secret"}', "more_body": False},
    ]
    sent: list[dict[str, Any]] = []
    downstream_called = False

    async def app(scope: dict[str, Any], receive: Any, send: Any) -> None:
        nonlocal downstream_called
        downstream_called = True

    async def receive() -> dict[str, Any]:
        return request_messages.pop(0)

    async def send(message: dict[str, Any]) -> None:
        sent.append(message)

    asyncio.run(dynamic_module.DynamicSseMiddleware(app)({"type": "http"}, receive, send))

    assert downstream_called is False
    assert sent[0]["status"] == 413
    assert b"secret" not in sent[1]["body"]


def _load_dynamic_middleware(monkeypatch: pytest.MonkeyPatch) -> tuple[ModuleType, ContextVar[Any]]:
    class BaseMiddleware:
        def __init__(self, app: Any) -> None:
            self.app = app

    class JsonResponse:
        def __init__(self, content: Any = None, status_code: int = 200) -> None:
            self.content = content
            self.status_code = status_code

        async def __call__(self, scope: dict[str, Any], receive: Any, send: Any) -> None:
            body = json.dumps(self.content).encode("utf-8")
            await send(
                {
                    "type": "http.response.start",
                    "status": self.status_code,
                    "headers": [(b"content-type", b"application/json"), (b"content-length", str(len(body)).encode())],
                }
            )
            await send({"type": "http.response.body", "body": body, "more_body": False})

    status = SimpleNamespace(
        HTTP_200_OK=200,
        HTTP_400_BAD_REQUEST=400,
        HTTP_403_FORBIDDEN=403,
        HTTP_413_REQUEST_ENTITY_TOO_LARGE=413,
        HTTP_502_BAD_GATEWAY=502,
    )
    auth_context: ContextVar[Any] = ContextVar("test_mcp_auth_context", default=None)

    _set_module(monkeypatch, "fastapi", status=status)
    _set_module(monkeypatch, "langboard_shared")
    _set_module(monkeypatch, "langboard_shared.core")
    _set_module(
        monkeypatch,
        "langboard_shared.core.routing",
        ApiErrorCode=SimpleNamespace(PE1001="permission_denied"),
        BaseMiddleware=BaseMiddleware,
        JsonResponse=JsonResponse,
    )
    _set_module(monkeypatch, "langboard_shared.domain")
    _set_module(monkeypatch, "langboard_shared.domain.models", McpToolGroup=object)
    _set_module(monkeypatch, "starlette")
    _set_module(monkeypatch, "starlette.types", Message=dict, Receive=Any, Send=Any)
    _set_module(monkeypatch, "langboard")
    _set_module(monkeypatch, "langboard.middlewares")
    _set_module(monkeypatch, "langboard.middlewares.McpAuthMiddleware", mcp_auth_context=auth_context)
    monkeypatch.setitem(sys.modules, "langboard.middlewares.ToolListFiltering", _MODULE)

    subject = Path(__file__).parents[2] / "langboard" / "middlewares" / "DynamicSseMiddleware.py"
    spec = spec_from_file_location("langboard_dynamic_sse_contract", subject)
    assert spec is not None and spec.loader is not None
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    return module, auth_context


def _set_module(monkeypatch: pytest.MonkeyPatch, name: str, **attributes: Any) -> ModuleType:
    module = ModuleType(name)
    module.__dict__.update(attributes)
    monkeypatch.setitem(sys.modules, name, module)
    return module
