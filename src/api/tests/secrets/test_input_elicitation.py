# ruff: noqa: F401, F811
"""Native URL rounds never trust client acceptance as secret completion."""

import json
from types import SimpleNamespace
import pytest
from fastmcp import Client, FastMCP
from fastmcp.client.elicitation import ElicitResult
from langboard.mcp_integration.Extensions import create_native_extension_provider
from langboard.mcp_integration.Server import McpServer
from langboard.mcp_tools.SecretReferenceMcp import request_secret_input, request_secret_rotation_input
from langboard.middlewares.McpAuthMiddleware import mcp_auth_context
from langboard.secrets import McpSecretInput, SecretInput
from langboard_shared.domain.services import DomainService
from mcp.types import ElicitResult as WireElicitResult
from mcp.types import InputRequiredResult
from pydantic import SecretStr
from test_input import board, flow, secrets


@pytest.mark.asyncio
@pytest.mark.parametrize("outcome", ["completed", "accepted-pending", "cancel"])
async def test_native_url_roundtrip_uses_server_completion(flow, monkeypatch, outcome):
    service, actor, _ = flow
    monkeypatch.setattr(DomainService, "secret_reference", property(lambda _: service.secret_reference))
    server = FastMCP("native-secret-url")
    server.add_provider(
        create_native_extension_provider(
            ["request_secret_input", "request_secret_rotation_input"], McpServer._wrap_tool
        )
    )
    urls = []

    async def consent(message, response_type, params, context):
        assert params.mode == "url" and response_type is None
        urls.append(params.url)
        uid = params.url.rsplit("/", 1)[-1]
        if outcome == "completed":
            _, challenge = SecretInput.open_input(service, actor, uid)
            SecretInput.complete_input(service, actor, uid, SecretStr("fixture-only-secret"), challenge)
        return ElicitResult(action="cancel" if outcome == "cancel" else "accept")

    token = mcp_auth_context.set({"user_or_bot": actor})
    try:
        async with Client(server, elicitation_handler=consent, mode="2026-07-28") as client:
            result = await client.call_tool(
                "request_secret_input", {"scope": "personal", "scope_uid": "me", "name": "native/key"}
            )
            assert len(urls) == 1
            expected = (
                "pending" if outcome == "accepted-pending" else "cancelled" if outcome == "cancel" else "completed"
            )
            assert result.structured_content["state"] == expected
            assert ("secret_ref" in result.structured_content) == (outcome == "completed")
            if outcome == "accepted-pending":
                assert result.structured_content["input_uid"] == urls[0].rsplit("/", 1)[-1]
            assert "fixture-only-secret" not in json.dumps(result.structured_content)
            if outcome == "completed":
                ref = result.structured_content["secret_ref"]
                rotation = await client.call_tool("request_secret_rotation_input", {"uri": ref, "expected_revision": 0})
                assert len(urls) == 2
                assert rotation.structured_content == {"state": "completed", "secret_ref": ref}
                assert service.secret_reference.get_metadata(actor, ref)["revision"] == 1
    finally:
        mcp_auth_context.reset(token)


def test_bound_round_rejects_target_or_actor_change_and_preserves_expiry(flow, monkeypatch):
    service, actor, board = flow
    ctx = SimpleNamespace(
        request_context=SimpleNamespace(
            protocol_version="2026-07-28",
            meta={"io.modelcontextprotocol/clientCapabilities": {"elicitation": {"url": {}}}},
        ),
        request_state=None,
        input_responses=None,
    )
    monkeypatch.setattr(McpSecretInput, "get_context", lambda: ctx)
    first = request_secret_input("personal", "me", "native/key", actor, service)
    assert isinstance(first, InputRequiredResult)
    ctx.request_state = first.request_state
    ctx.input_responses = {"secret": WireElicitResult(action="accept", content={"secret_ref": "forged"})}
    with pytest.raises(ValueError):
        request_secret_input("personal", "me", "changed", actor, service)
    with pytest.raises(ValueError):
        request_secret_input("personal", "me", "native/key", board[3], service)
    assert request_secret_input("personal", "me", "native/key", actor, service) == {
        "state": "pending",
        "input_uid": first.request_state,
    }
    ctx.request_state = None
    with pytest.raises(ValueError):
        request_secret_input("personal", "me", "native/key", actor, service)
    ctx.request_state = first.request_state
    # A retry must not mint a new input if protocol/capability metadata changes.
    ctx.request_context.protocol_version = "2025-11-25"
    ctx.request_context.meta = {}
    assert request_secret_input("personal", "me", "native/key", actor, service) == {
        "state": "pending",
        "input_uid": first.request_state,
    }
    with pytest.raises(ValueError):
        request_secret_rotation_input("secret://ref/forged", 0, actor, service)
    monkeypatch.setattr(SecretInput, "time", lambda: 10**12)
    assert request_secret_input("personal", "me", "native/key", actor, service) == {"state": "expired"}
