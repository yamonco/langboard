"""Signed Bearer requests exercise native OAuth HTTP gates, without a live IdP."""

import json
import time
from types import SimpleNamespace
from unittest.mock import Mock
import pytest
from fastmcp.server.auth.oauth_proxy.models import JTIMapping, UpstreamTokenSet
from fastmcp.server.auth.oidc_proxy import OIDCConfiguration, OIDCProxy
from fastmcp.server.auth.providers.jwt import JWTVerifier
from joserfc import jwk, jwt
from key_value.aio.stores.memory import MemoryStore
from langboard.mcp_integration import OAuth, Server
from langboard.mcp_integration.Tool import McpTool
from langboard.middlewares.McpAuthMiddleware import mcp_auth_context
from starlette.testclient import TestClient


@pytest.mark.parametrize(
    "failure",
    [
        None,
        "signature",
        "audience",
        "scope",
        "issuer",
        "subject",
        "inactive",
        "deleted",
        "expired",
        "upstream_audience",
        "missing_mapping",
        "native_scope",
    ],
)
async def test_signed_bearer_http_checks_identity_scope_and_revocation(monkeypatch, failure):
    configuration = OIDCConfiguration(
        issuer="https://id.example",
        authorization_endpoint="https://id.example/authorize",
        token_endpoint="https://id.example/token",
        jwks_uri="https://id.example/jwks",
        response_types_supported=["code"],
        subject_types_supported=["public"],
        id_token_signing_alg_values_supported=["HS256"],
    )
    monkeypatch.setattr(OIDCProxy, "get_oidc_configuration", lambda *args, **kwargs: configuration)
    upstream_key = "isolated-test-upstream-key-at-least-32-characters"
    provider = OAuth.LangboardOIDCProxy(
        config_url="https://id.example/.well-known/openid-configuration",
        client_id="native-fixture",
        client_secret="isolated-test-client-secret",
        base_url="https://board.example/mcp/oauth",
        jwt_signing_key="isolated-test-native-signing-key-at-least-32-characters",
        token_verifier=JWTVerifier(
            public_key=upstream_key, algorithm="HS256", issuer="https://id.example", audience="native-fixture"
        ),
        verify_id_token=True,
        valid_scopes=["openid", "mcp:access"],
        client_storage=MemoryStore(),
    )
    provider.get_routes(mcp_path="/stream")
    now = time.time()
    upstream_claims = {
        "iss": "https://other.example" if failure == "issuer" else "https://id.example",
        "aud": "foreign-client" if failure == "upstream_audience" else "native-fixture",
        "sub": "unlinked-sub" if failure == "subject" else "linked-sub",
        "iat": int(now),
        "exp": int(now) - 3600 if failure == "expired" else int(now) + 3600,
    }
    id_token = jwt.encode({"alg": "HS256"}, upstream_claims, jwk.OctKey.import_key(upstream_key))
    scopes = ["openid"] if failure == "scope" else ["openid", "mcp:access"]
    await provider._upstream_token_store.put(
        key="upstream-fixture",
        value=UpstreamTokenSet(
            upstream_token_id="upstream-fixture",
            access_token="isolated-upstream-access-token",
            refresh_token=None,
            refresh_token_expires_at=None,
            expires_at=now + 3600,
            token_type="Bearer",
            scope=" ".join(scopes),
            client_id="native-client",
            created_at=now,
            raw_token_data={"id_token": id_token},
        ),
    )
    await provider._jti_mapping_store.put(
        key="native-fixture-jti",
        value=JTIMapping(
            jti="native-fixture-jti",
            upstream_token_id="upstream-fixture",
            created_at=now,
        ),
    )
    if failure == "missing_mapping":
        await provider._jti_mapping_store.delete(key="native-fixture-jti")
    bearer = provider.jwt_issuer.issue_access_token(
        client_id="native-client", scopes=["openid"] if failure == "native_scope" else scopes, jti="native-fixture-jti"
    )
    if failure in {"signature", "audience"}:
        from fastmcp.server.auth.jwt_issuer import JWTIssuer

        alternate = JWTIssuer(
            issuer=provider.jwt_issuer.issuer,
            audience="https://foreign.example/stream" if failure == "audience" else provider.jwt_issuer.audience,
            signing_key=b"untrusted-test-signing-key-at-least-32-characters"
            if failure == "signature"
            else provider.jwt_issuer._signing_key,
        )
        bearer = alternate.issue_access_token(client_id="native-client", scopes=scopes, jti="native-fixture-jti")

    user = SimpleNamespace(
        activated_at=None if failure == "inactive" else object(), deleted_at=object() if failure == "deleted" else None
    )
    lookup = Mock(
        side_effect=lambda provider, subject, issuer: user
        if subject == "linked-sub" and issuer == "https://id.example"
        else None
    )
    service = SimpleNamespace(identity_link=SimpleNamespace(get_user_by_provider_external_id=lookup), close=Mock())
    monkeypatch.setattr(OAuth, "DomainService", lambda: service)
    monkeypatch.setattr(OAuth, "create_oauth_provider", lambda: provider)
    calls = []

    async def probe() -> dict:
        """Record a command reaching the authenticated native domain boundary."""
        principal = mcp_auth_context.get()
        assert principal["user_or_bot"] is user and principal["transport"] == "oauth"
        assert "tool_group" not in principal
        calls.append(True)
        return {"applied": True}

    monkeypatch.setattr(McpTool, "get_tools", lambda: {"fixture_probe": {"handler": probe, "description": "Probe"}})
    monkeypatch.setattr(McpTool, "get_tool", lambda name: None)
    monkeypatch.setattr(Server.McpServer, "_wrap_tool", lambda name, handler: handler)
    before = mcp_auth_context.get()
    app = Server.McpServer.get_oauth_http_app()
    with TestClient(app, base_url="https://board.example") as client:
        response = client.post(
            "/stream",
            headers={"Authorization": f"Bearer {bearer}", "Accept": "application/json, text/event-stream"},
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {"name": "fixture_probe", "arguments": {}},
            },
        )
        if failure is None:
            assert response.status_code == 200
            payload = json.loads(next(line[6:] for line in response.text.splitlines() if line.startswith("data: ")))
            assert payload["result"]["structuredContent"] == {"applied": True}
            assert calls == [True]
            assert lookup.call_args.args[1:] == ("linked-sub", "https://id.example")
            user.activated_at = None
            revoked = client.post(
                "/stream",
                headers={"Authorization": f"Bearer {bearer}", "Accept": "application/json, text/event-stream"},
                json={
                    "jsonrpc": "2.0",
                    "id": 2,
                    "method": "tools/call",
                    "params": {"name": "fixture_probe", "arguments": {}},
                },
            )
            assert calls == [True]
            assert revoked.status_code == 200
            denial = json.loads(next(line[6:] for line in revoked.text.splitlines() if line.startswith("data: ")))
            assert "error" in denial or denial["result"]["isError"] is True
        else:
            assert calls == []
            if failure in {
                "signature",
                "audience",
                "scope",
                "issuer",
                "expired",
                "upstream_audience",
                "missing_mapping",
                "native_scope",
            }:
                lookup.assert_not_called()
            assert response.status_code in {200, 401, 403}
            if response.status_code == 200:
                payload = json.loads(next(line[6:] for line in response.text.splitlines() if line.startswith("data: ")))
                assert "error" in payload or payload["result"]["isError"] is True
    assert mcp_auth_context.get() is before
