"""Native command receipts without host-specific identity or business orchestration."""

import json
import re
from typing import Any, Protocol
from .presentation import CARD_PRESENTATION_KEY, validate_card_presentation


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

    async def create_card(
        self, project_uid: str, column_uid: str, title: str, *,
        description: str | None = None, assign_user_uids: list[str] | None = None,
    ) -> dict[str, Any]:
        """Create through native authority in an explicitly selected active column.

        Use the host's approved workflow mapping, not a localized column name.
        Creation is not idempotent: never automatically replay a lost response.
        Presentation is a separate native write after the returned card UID.
        """
        for value in (project_uid, column_uid):
            if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", value):
                raise ValueError("A native board and destination column are required")
        if not isinstance(title, str) or not title.strip():
            raise ValueError("A card title is required")
        result = await self._transport.call(
            "create_card", {
                "project_uid": project_uid, "column_uid": column_uid, "title": title,
                "description": description, "assign_user_uids": assign_user_uids,
            }, mutation=True,
        )
        if not isinstance(result, dict) or not isinstance(result.get("uid"), str) or not result["uid"]:
            raise MutationOutcomeUnknown("Card creation receipt unavailable; inspect state before retrying")
        return result

    async def preview_work_plan(self, plan: dict[str, Any]) -> dict[str, Any]:
        result = await self._transport.call(
            "preview_card_work_plan", {"project_uid": plan["project_uid"], "plan": plan}
        )
        if not isinstance(result, dict) or not re.fullmatch(r"[0-9a-f]{64}", str(result.get("revision", ""))):
            raise RuntimeError("Langboard returned an invalid work plan preview")
        return result

    async def apply_work_plan(self, plan: dict[str, Any], expected_revision: str, request_id: str) -> dict[str, Any]:
        if not re.fullmatch(r"[0-9a-f]{64}", expected_revision):
            raise ValueError("A reviewed work plan revision is required")
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", request_id):
            raise ValueError("A stable work plan request ID is required")
        result = await self._transport.call(
            "apply_card_work_plan",
            {
                "project_uid": plan["project_uid"],
                "plan": plan,
                "expected_revision": expected_revision,
                "request_id": request_id,
            },
            mutation=True,
        )
        if (
            not isinstance(result, dict)
            or result.get("all_succeeded") is not True
            or result.get("applied_revision") != expected_revision
            or type(result.get("replayed")) is not bool
        ):
            raise MutationOutcomeUnknown(
                "Langboard returned an invalid work plan receipt; inspect state before retrying"
            )
        return result

    async def set_card_presentation(
        self, project_uid: str, card_uid: str, presentation: dict[str, Any]
    ) -> dict[str, Any]:
        """Attach an app display type/origin after native creation; never changes card authority.

        The server validates the v1 contract. Name and description are English
        fallbacks; translations are optional. App metadata is self-declared,
        not proof of provider identity. Read back before retrying ambiguous writes.
        """
        value = json.dumps(presentation, ensure_ascii=False, separators=(",", ":"))
        validate_card_presentation(value)
        result = await self._transport.call(
            "save_public_card_metadata",
            {"project_uid": project_uid, "card_uid": card_uid, "key": CARD_PRESENTATION_KEY, "value": value},
            mutation=True,
        )
        returned = result.get("value") if isinstance(result, dict) else None
        valid = (
            isinstance(result, dict)
            and result.get("key") == CARD_PRESENTATION_KEY
            and result.get("total_chars") == len(value)
            and isinstance(returned, str)
            and bool(returned)
            and (
                (result.get("truncated") is False and returned == value)
                or (result.get("truncated") is True and len(returned) < len(value) and value.startswith(returned))
            )
        )
        if not valid:
            raise MutationOutcomeUnknown("Card presentation receipt unavailable; read metadata before retrying")
        return result

    async def get_connection_context(
        self, project_uid: str, *, card_uid: str | None = None, cursor: str | None = None
    ) -> dict[str, Any]:
        """Read one authorized page of 1:N resources; never infer grants from metadata.

        Resource identity includes connection_uid and resource_uid. The caller
        chooses whether to request the next page; no provider names or credentials
        are required by this client.
        """
        arguments = {"project_uid": project_uid}
        if card_uid is not None:
            arguments["card_uid"] = card_uid
        if cursor is not None:
            arguments["cursor"] = cursor
        result = await self._transport.call("get_connection_context", arguments)
        resources = result.get("resources") if isinstance(result, dict) else None
        if (
            not isinstance(result, dict)
            or result.get("project_uid") != project_uid
            or not isinstance(resources, dict)
            or not isinstance(resources.get("items"), list)
            or "next_cursor" not in resources
            or resources["next_cursor"] is not None and not isinstance(resources["next_cursor"], str)
        ):
            raise RuntimeError("Langboard returned an invalid connection context")
        return result
