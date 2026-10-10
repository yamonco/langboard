"""Native normalized payloads and reviewer evidence retain their meaning."""

from types import SimpleNamespace
import pytest
from fastmcp import Client
from langboard.mcp_integration.ContentOutputs import CONTENT_OUTPUTS
from langboard.mcp_integration.Server import McpServer
from langboard.mcp_integration.Tool import McpTool
from langboard.mcp_tools.CardMcp import _public_content_block
from langboard.middlewares.McpAuthMiddleware import mcp_auth_context
from langboard_shared.domain.contracts.content_blocks import ContentBlockType, build_payload, check_revision
from langboard_shared.domain.services.CardVerification import VerificationConflict


@pytest.mark.parametrize(
    "kind,payload",
    [
        ("code", {"language": "python", "source": "print('한글')"}),
        ("diagram", {"engine": "mermaid", "source": "graph TD; A-->B"}),
        ("rich_text", {"text": "문서"}),
    ],
)
def test_native_block_payload_is_typed_without_changing_literal_content(kind, payload):
    block = SimpleNamespace(
        get_uid=lambda: "block",
        order=0,
        revision=1,
        updated_at=None,
        block_type=kind,
        payload=build_payload(ContentBlockType(kind), payload),
    )
    expected = {"content_block": _public_content_block(block)}
    model = CONTENT_OUTPUTS["create_card_content_block"]
    assert model.model_validate(expected).model_dump(mode="json") == expected


@pytest.mark.parametrize(
    "profile,kind",
    [("agent", "verification"), ("raw", "block"), ("compatibility", "verification"), ("compatibility", "block")],
)
async def test_presave_revision_conflicts_are_structured_without_writes(monkeypatch, profile, kind):
    name = "record_card_verification_evidence" if kind == "verification" else "update_card_content_block"
    effects = []

    def handler(value: int) -> dict:
        if kind == "verification":
            raise VerificationConflict("stale card source")
        check_revision(value, 2)
        effects.append(value)
        return {}

    metadata = {"handler": handler, "description": "Change", "exclude": [], "accessible_type": "all"}
    monkeypatch.setattr(McpTool, "get_tools", lambda: {name: metadata})
    monkeypatch.setattr(McpTool, "get_tool", lambda tool_name: metadata if tool_name == name else None)
    monkeypatch.setattr(McpServer, "_validate_auth", lambda *args: True)
    monkeypatch.setattr(McpServer, "_validate_role", lambda *args, **kwargs: True)
    _, server = McpServer.get_http_app(profile)
    token = mcp_auth_context.set(
        {"user_or_bot": object(), "tool_group": SimpleNamespace(activated_at=object(), tools=[name])}
    )
    try:
        async with Client(server) as client:
            result = await client.call_tool(
                "call_raw_tool" if profile == "raw" else name,
                {"name": name, "arguments": {"value": 1}} if profile == "raw" else {"value": 1},
                raise_on_error=False,
            )
            assert result.is_error
            assert not effects
            receipt = (result.meta or {}).get("mutation_receipt")
            if profile == "compatibility":
                assert receipt is None
            else:
                assert receipt["outcome"] == "not_applied"
                assert receipt["revision_conflict"] is True
                assert receipt["retryable"] is False
                assert receipt["next_action"] == "read_and_review"
    finally:
        mcp_auth_context.reset(token)


def test_native_verification_record_projection_retains_declared_evidence():
    from langboard_shared.core.types import SafeDateTime, SnowflakeID
    from langboard_shared.domain.models import CardVerificationRecord
    from langboard_shared.domain.services.factory.CardService import CardService

    record = CardVerificationRecord(
        id=123,
        card_id=456,
        source_change_seq=7,
        decision="partial",
        recorded_by_user_id=SnowflakeID(789),
        recorded_by_bot_id=None,
        created_at=SafeDateTime.now(),
        evidence=[
            {"reference": "test:receipt", "source_revision": "revision", "environment": "canary", "checkitem_uid": None}
        ],
        required_checkitem_uids=[],
    )
    expected = {"verification": CardService._verification_projection(record)}
    assert (
        CONTENT_OUTPUTS["record_card_verification_evidence"].model_validate(expected).model_dump(mode="json")
        == expected
    )
