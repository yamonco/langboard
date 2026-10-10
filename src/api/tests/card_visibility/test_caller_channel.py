"""Credential and transport boundaries must not turn an agent into a human."""

from types import SimpleNamespace
import pytest
from langboard_shared.core.security import AuthSecurity
from langboard_shared.core.security.CollaborationChannel import CollaborationChannel
from langboard_shared.domain.models import Bot, User
from langboard_shared.helpers import MiddlewareHelper
from langboard_shared.security import Auth
from starlette.requests import Request


@pytest.mark.parametrize(
    "credential", ["session", "user_token", "bot_token", "api_key", "oidc", "invalid", "key_session"]
)
def test_auth_channel_is_derived_from_validated_credentials(monkeypatch, credential):
    user = User.model_construct(id=1, is_admin=True)
    bot = Bot.model_construct(id=2)
    monkeypatch.setattr(Auth, "validate", lambda _: user if credential in ("session", "key_session") else 401)
    monkeypatch.setattr(Auth, "validate_user_by_api_token", lambda _: user if credential == "user_token" else 401)
    monkeypatch.setattr(Auth, "validate_bot", lambda _: bot if credential == "bot_token" else 401)
    monkeypatch.setattr(
        Auth, "validate_user_by_api_key", lambda _: (user, object()) if credential == "api_key" else 401
    )
    monkeypatch.setattr(MiddlewareHelper, "_validate_oidc_user", lambda _: user if credential == "oidc" else None)
    headers = [(b"x-collaboration-channel", b"human_ui")]
    if credential in ("user_token", "bot_token"):
        headers.append((AuthSecurity.API_TOKEN_HEADER.lower().encode(), b"token"))
    if credential in ("api_key", "key_session"):
        headers.append((AuthSecurity.API_KEY_HEADER.lower().encode(), b"key"))
    scope = {"type": "http", "headers": headers, "collaboration_channel": CollaborationChannel.HumanUI}
    result = MiddlewareHelper.validate_auth(scope)
    expected = CollaborationChannel.HumanUI if credential == "session" else CollaborationChannel.Api
    if credential == "bot_token":
        expected = CollaborationChannel.Bot
        assert result is bot
    elif credential in ("invalid", "key_session"):
        # An explicitly invalid API key must not fall back to a valid browser session.
        assert result == 401
    else:
        assert result is user
    assert scope["collaboration_channel"] == expected


@pytest.mark.parametrize("channel", [CollaborationChannel.Api, CollaborationChannel.Mcp, None])
async def test_batch_preserves_server_channel_and_ignores_form_spoofing(monkeypatch, channel):
    from langboard.routes.batcher import BatchRunner
    from langboard.routes.batcher.BatchForm import BatchFormRequestSchema

    actor = User.model_construct(id=1)
    scope = {"type": "http", "headers": [], "auth": actor}
    if channel is not None:
        scope["collaboration_channel"] = channel
    seen = []

    async def app(inner_scope, receive, send):
        seen.append(inner_scope)
        await send({"type": "http.response.start", "status": 200})
        await send({"type": "http.response.body", "body": b"{}"})

    monkeypatch.setattr(BatchRunner, "resolve_batch_request", lambda *_: ({"permission": "write"}, "/fixture", None))
    monkeypatch.setattr(BatchRunner.AppRouter, "get_app", lambda: app)
    schema = BatchFormRequestSchema(
        path_or_api_name="fixture", method="POST", form={"collaboration_channel": "human_ui"}
    )
    result = await BatchRunner.execute_batch_request_schemas(Request(scope), [schema], actor, None)
    assert result[0]["status"] == 200
    assert seen[0]["collaboration_channel"] == (channel or CollaborationChannel.Api)
    assert seen[0]["auth"] is actor


async def test_legacy_mcp_overrides_native_session_and_resets_context(monkeypatch):
    from langboard.middlewares.McpAuthMiddleware import McpAuthMiddleware, mcp_auth_context

    actor = User.model_construct(id=1, is_admin=True)
    group = SimpleNamespace(activated_at=object(), user_id=None)
    service = SimpleNamespace(mcp_tool_group=SimpleNamespace(get_by_id_like=lambda _: group))
    scope = {"type": "http", "headers": [], "collaboration_channel": CollaborationChannel.HumanUI}

    async def app(scope, receive, send):
        assert scope["collaboration_channel"] == CollaborationChannel.Mcp
        assert mcp_auth_context.get()["collaboration_channel"] == CollaborationChannel.Mcp
        assert mcp_auth_context.get()["user_or_bot"] is actor
        raise RuntimeError("fixture handler failure")

    previous = mcp_auth_context.get()
    with pytest.raises(RuntimeError, match="fixture handler failure"):
        await McpAuthMiddleware(app)._validate_and_dispatch(scope, None, None, actor, None, "fixture", service)
    assert mcp_auth_context.get() is previous
