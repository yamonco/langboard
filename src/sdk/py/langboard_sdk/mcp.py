"""Adapter for an already authenticated MCP client, with no provider assumptions."""

from typing import Any
from .client import MutationOutcomeUnknown


class NativeCommandError(RuntimeError):
    """Keep the server error result; callers must inspect state before replaying writes."""

    def __init__(self, command: str, result: Any) -> None:
        super().__init__("Native command returned an error; inspect result and current state before retrying")
        self.command = command
        self.result = result


class McpTransport:
    """Use a caller-owned connected FastMCP-style session; do not copy credentials or lifecycle."""

    def __init__(self, client: Any) -> None:
        self._client = client

    async def call(self, name: str, arguments: dict[str, Any], *, mutation: bool = False) -> Any:
        try:
            result = await self._client.call_tool(name, arguments, raise_on_error=False)
        except Exception as error:
            if mutation:
                raise MutationOutcomeUnknown("Mutation response unavailable; inspect state before replaying the same request") from error
            raise
        if getattr(result, "is_error", None) is True:
            raise NativeCommandError(name, result)
        value = getattr(result, "structured_content", None)
        if not isinstance(value, dict):
            if mutation:
                raise MutationOutcomeUnknown("Mutation receipt unavailable; inspect state before replaying the same request")
            raise RuntimeError("Native command returned no structured object")
        return value
