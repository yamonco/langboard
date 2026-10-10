"""Native command receipts without host-specific identity or business orchestration."""

import re
from typing import Any, Protocol


class CommandTransport(Protocol):
    async def call(self, name: str, arguments: dict[str, Any], *, mutation: bool = False) -> Any:
        """Call an authorized native command; never silently retry an ambiguous write."""
        ...


class MutationOutcomeUnknown(RuntimeError):
    """Inspect current server state before replaying the same reviewed request."""


class LangboardClient:
    """Share protocol validation while delegating domain transactions to Langboard."""

    def __init__(self, transport: CommandTransport) -> None:
        self._transport = transport

    async def preview_work_plan(self, plan: dict[str, Any]) -> dict[str, Any]:
        result = await self._transport.call(
            "preview_card_work_plan", {"project_uid": plan["project_uid"], "plan": plan}
        )
        if not isinstance(result, dict) or not re.fullmatch(r"[0-9a-f]{64}", str(result.get("revision", ""))):
            raise RuntimeError("Langboard returned an invalid work plan preview")
        return result

    async def apply_work_plan(
        self, plan: dict[str, Any], expected_revision: str, request_id: str
    ) -> dict[str, Any]:
        if not re.fullmatch(r"[0-9a-f]{64}", expected_revision):
            raise ValueError("A reviewed work plan revision is required")
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", request_id):
            raise ValueError("A stable work plan request ID is required")
        result = await self._transport.call(
            "apply_card_work_plan",
            {"project_uid": plan["project_uid"], "plan": plan, "expected_revision": expected_revision, "request_id": request_id},
            mutation=True,
        )
        if (
            not isinstance(result, dict)
            or result.get("all_succeeded") is not True
            or result.get("applied_revision") != expected_revision
            or type(result.get("replayed")) is not bool
        ):
            raise MutationOutcomeUnknown("Langboard returned an invalid work plan receipt; inspect state before retrying")
        return result
