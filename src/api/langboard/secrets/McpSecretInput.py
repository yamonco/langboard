"""Native URL input requests reuse the authenticated one-use browser session."""

from fastmcp.server.dependencies import get_context
from langboard_shared.domain.services.factory.SecretReferenceService import SecretReferenceUnavailable
from mcp.types import ElicitRequestURLParams, InputRequiredResult
from .SecretInput import _context, cancel_input, input_status


def request_input(service, actor, target, begin):
    try:
        ctx = get_context()
    except RuntimeError:
        return begin()
    if ctx.input_responses is not None and ctx.request_state is None:
        raise SecretReferenceUnavailable()
    if ctx.request_state is not None:
        uid = ctx.request_state
        context = _context(service, actor, uid)
        if any(context.get(key) != value for key, value in target.items()):
            raise SecretReferenceUnavailable()
        status = input_status(service, actor, uid)
        response = (ctx.input_responses or {}).get("secret")
        if status["state"] == "pending" and response is not None and response.action in {"decline", "cancel"}:
            return cancel_input(service, actor, uid)
        # Client acceptance is not proof of browser submission. The server's
        # persisted input state remains authoritative, including expiry.
        if status["state"] == "pending":
            status["input_uid"] = uid
        return status

    rc = ctx.request_context
    capabilities = (rc.meta or {}).get("io.modelcontextprotocol/clientCapabilities", {}) if rc else {}
    elicitation = capabilities.get("elicitation", {}) if isinstance(capabilities, dict) else {}
    supports_url = isinstance(elicitation, dict) and isinstance(elicitation.get("url"), dict)
    if rc is None or rc.protocol_version != "2026-07-28" or not supports_url:
        return begin()

    pending = begin()
    return InputRequiredResult(
        input_requests={
            "secret": {
                "method": "elicitation/create",
                "params": ElicitRequestURLParams(
                    mode="url",
                    message="Enter the secret directly in Langboard. It will not be sent through MCP.",
                    url=pending["input_url"],
                    elicitation_id=pending["input_uid"],
                ),
            }
        },
        request_state=pending["input_uid"],
    )
