import json
import re
from collections.abc import Collection
from typing import Any


class BodyLimitExceeded(ValueError):
    """Raised when a buffered MCP body exceeds its configured byte limit."""


class UnsafeToolListPayload(ValueError):
    """Raised when a tools/list response cannot be filtered without leaking tools."""


class BoundedBodyBuffer:
    """Collect byte chunks while enforcing a hard upper bound."""

    def __init__(self, limit: int) -> None:
        if limit <= 0:
            raise ValueError("Body buffer limit must be positive")
        self._limit = limit
        self._body = bytearray()

    def append(self, chunk: bytes) -> None:
        """Append one body chunk or fail before retaining an oversized body."""

        if len(self._body) + len(chunk) > self._limit:
            raise BodyLimitExceeded(f"MCP body exceeds the {self._limit}-byte limit")
        self._body.extend(chunk)

    def getvalue(self) -> bytes:
        """Return the buffered body as immutable bytes."""

        return bytes(self._body)


def is_tools_list_request(body: bytes) -> bool:
    """Return whether a complete JSON-RPC request invokes tools/list."""

    try:
        request = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return False
    if isinstance(request, dict):
        return request.get("method") == "tools/list"
    if isinstance(request, list):
        return any(isinstance(item, dict) and item.get("method") == "tools/list" for item in request)
    return False


def filter_tools_list_response(body: bytes, content_type: str, allowed_tools: Collection[str]) -> bytes:
    """Filter a complete JSON or SSE tools/list response to the exact allowlist."""

    media_type = content_type.partition(";")[0].strip().lower()
    if media_type == "text/event-stream":
        return _filter_sse_document(body, frozenset(allowed_tools))
    return _filter_json_document(body, frozenset(allowed_tools))


def _filter_json_document(body: bytes, allowed_tools: frozenset[str]) -> bytes:
    try:
        payload = json.loads(body.decode("utf-8"))
        filtered = _filter_rpc_payload(payload, allowed_tools)
    except (UnicodeDecodeError, json.JSONDecodeError, TypeError, KeyError) as exc:
        raise UnsafeToolListPayload("Invalid JSON tools/list response") from exc
    return _dump_json(filtered).encode("utf-8")


def _filter_sse_document(body: bytes, allowed_tools: frozenset[str]) -> bytes:
    try:
        document = body.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise UnsafeToolListPayload("Invalid UTF-8 SSE tools/list response") from exc

    parts = re.split(r"(\r?\n\r?\n)", document)
    filtered_parts: list[str] = []
    found_rpc_message = False

    for part in parts:
        if not part or re.fullmatch(r"\r?\n\r?\n", part):
            filtered_parts.append(part)
            continue

        lines = part.splitlines(keepends=True)
        data_indexes = [index for index, line in enumerate(lines) if line.startswith("data:")]
        if not data_indexes:
            filtered_parts.append(part)
            continue

        data = "\n".join(_sse_data_value(lines[index]) for index in data_indexes)
        try:
            payload = json.loads(data)
            filtered, changed = _filter_rpc_payload_with_change(payload, allowed_tools)
        except (json.JSONDecodeError, TypeError, KeyError) as exc:
            raise UnsafeToolListPayload("Invalid SSE tools/list response") from exc

        found_rpc_message = True
        if not changed:
            filtered_parts.append(part)
            continue

        first_data_index = data_indexes[0]
        newline = _line_ending(lines[first_data_index])
        lines[first_data_index] = f"data: {_dump_json(filtered)}{newline}"
        for index in reversed(data_indexes[1:]):
            del lines[index]
        filtered_parts.append("".join(lines))

    if not found_rpc_message:
        raise UnsafeToolListPayload("SSE tools/list response contains no JSON-RPC message")
    return "".join(filtered_parts).encode("utf-8")


def _filter_rpc_payload(payload: Any, allowed_tools: frozenset[str]) -> Any:
    filtered, _ = _filter_rpc_payload_with_change(payload, allowed_tools)
    return filtered


def _filter_rpc_payload_with_change(payload: Any, allowed_tools: frozenset[str]) -> tuple[Any, bool]:
    if isinstance(payload, list):
        filtered_messages: list[dict[str, Any]] = []
        changed = False
        found_tools_result_or_error = False
        for message in payload:
            filtered_message, message_changed = _filter_rpc_message(message, allowed_tools, require_tools=False)
            filtered_messages.append(filtered_message)
            changed = changed or message_changed
            found_tools_result_or_error = found_tools_result_or_error or (
                isinstance(message, dict)
                and ("error" in message or (isinstance(message.get("result"), dict) and "tools" in message["result"]))
            )
        if not found_tools_result_or_error:
            raise KeyError("JSON-RPC batch contains no tools/list result or error")
        return filtered_messages, changed
    return _filter_rpc_message(payload, allowed_tools, require_tools=True)


def _filter_rpc_message(
    payload: Any,
    allowed_tools: frozenset[str],
    *,
    require_tools: bool,
) -> tuple[dict[str, Any], bool]:
    if not isinstance(payload, dict):
        raise TypeError("JSON-RPC response must be an object")

    if "error" in payload:
        return payload, False

    result = payload.get("result")
    if not isinstance(result, dict) or "tools" not in result:
        if require_tools:
            raise KeyError("JSON-RPC tools/list response is missing result.tools")
        return payload, False

    tools = result["tools"]
    if not isinstance(tools, list):
        raise TypeError("JSON-RPC result.tools must be a list")

    filtered_tools: list[dict[str, Any]] = []
    for tool in tools:
        if not isinstance(tool, dict) or not isinstance(tool.get("name"), str):
            raise TypeError("Every MCP tool must be an object with a string name")
        if tool["name"] in allowed_tools:
            filtered_tools.append(tool)

    filtered_result = {**result, "tools": filtered_tools}
    return {**payload, "result": filtered_result}, True


def _sse_data_value(line: str) -> str:
    value = line.removeprefix("data:").rstrip("\r\n")
    return value.removeprefix(" ")


def _line_ending(line: str) -> str:
    if line.endswith("\r\n"):
        return "\r\n"
    if line.endswith("\n"):
        return "\n"
    return ""


def _dump_json(payload: Any) -> str:
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
