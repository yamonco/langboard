"""Adapter for an already authenticated MCP client, with no provider assumptions."""

from typing import Any
from .client import MutationOutcomeUnknown


class McpTransport:
    """Use a caller-owned connected MCP session; do not copy credentials or lifecycle."""

    def __init__(self, client: Any) -> None:
        self._client = client

    async def call(self, name: str, arguments: dict[str, Any], *, mutation: bool = False) -> Any:
        try:
            result = await self._client.call_tool(name, arguments)
        except (TimeoutError, ConnectionError, OSError) as error:
            if mutation:
                raise MutationOutcomeUnknown("Mutation response unavailable; inspect state before replaying the same request") from error
            raise
        if result.is_error:
            raise RuntimeError("Native command rejected; inspect the returned MCP error")
        value = result.structured_content
        if not isinstance(value, dict):
            if mutation:
                raise MutationOutcomeUnknown("Mutation receipt unavailable; inspect state before replaying the same request")
            raise RuntimeError("Native command returned no structured object")
        return value
