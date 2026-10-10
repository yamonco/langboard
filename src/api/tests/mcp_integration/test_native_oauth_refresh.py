"""Exercise overlapping refresh exchanges against native FastMCP rotation."""

import asyncio
import time
from contextlib import asynccontextmanager
from types import SimpleNamespace
import pytest
from fastmcp.server.auth.oauth_proxy.proxy import JTIMapping, RefreshTokenMetadata, UpstreamTokenSet, _hash_token
from fastmcp.server.auth.oidc_proxy import OIDCConfiguration, OIDCProxy
from key_value.aio.stores.memory import MemoryStore
from langboard.mcp_integration.OAuth import LangboardOIDCProxy
from mcp.server.auth.provider import TokenError
from mcp.shared.auth import OAuthClientInformationFull


@pytest.mark.parametrize("scope_case", ["unchanged", "broadened", "narrowed", "client_expansion"])
@pytest.mark.parametrize("upstream_failure", [False, True])
async def test_concurrent_exchange_consumes_refresh_once(monkeypatch, upstream_failure, scope_case):
    """Two requests may load first; only one can exchange the loaded refresh."""
    discovery = OIDCConfiguration(
        issuer="https://invalid.example",
        authorization_endpoint="https://invalid.example/authorize",
        token_endpoint="https://invalid.example/token",
        jwks_uri="https://invalid.example/jwks",
        response_types_supported=["code"],
        subject_types_supported=["public"],
        id_token_signing_alg_values_supported=["RS256"],
    )
    monkeypatch.setattr(OIDCProxy, "get_oidc_configuration", lambda *args: discovery)
    proxy = LangboardOIDCProxy(
        config_url="https://invalid.example/discovery",
        client_id="isolated",
        client_secret="isolated-secret",
        base_url="https://invalid.example",
        jwt_signing_key="isolated-test-signing-material-not-production",
        client_storage=MemoryStore(),
        verify_id_token=False,
    )
    proxy.set_mcp_path("/mcp")
    client = OAuthClientInformationFull(client_id="isolated", redirect_uris=["https://invalid.example/callback"])
    now = time.time()
    approved = ["openid", "profile"] if scope_case == "narrowed" else ["openid"]
    requested = ["openid"]
    upstream_scopes = "openid profile mcp:access" if scope_case != "unchanged" else "openid"
    token = proxy.jwt_issuer.issue_refresh_token(
        client_id="isolated", scopes=approved, jti="refresh-jti", expires_in=120
    )
    await proxy._refresh_token_store.put(
        key=_hash_token(token),
        value=RefreshTokenMetadata(client_id="isolated", scopes=approved, expires_at=int(now) + 120, created_at=now),
        ttl=120,
    )
    await proxy._jti_mapping_store.put(
        key="refresh-jti", value=JTIMapping(jti="refresh-jti", upstream_token_id="upstream", created_at=now), ttl=120
    )
    await proxy._upstream_token_store.put(
        key="upstream",
        value=UpstreamTokenSet(
            upstream_token_id="upstream",
            access_token="isolated-access",
            refresh_token="isolated-upstream-refresh",
            refresh_token_expires_at=now + 120,
            expires_at=now + 60,
            token_type="Bearer",
            scope=" ".join(approved),
            client_id="isolated",
            created_at=now,
            raw_token_data={},
        ),
        ttl=120,
    )
    entered = asyncio.Event()
    release = asyncio.Event()
    calls = 0

    async def refresh_token(**kwargs):
        nonlocal calls
        assert kwargs["scope"] == "openid"
        calls += 1
        if upstream_failure and calls == 1:
            raise RuntimeError("Isolated upstream failure")
        entered.set()
        await release.wait()
        return {
            "access_token": "isolated-new-access",
            "refresh_token": "isolated-upstream-refresh",
            "expires_in": 60,
            "scope": upstream_scopes,
            "refresh_expires_in": 120,
        }

    @asynccontextmanager
    async def oauth_client():
        yield SimpleNamespace(refresh_token=refresh_token)

    monkeypatch.setattr(proxy, "_upstream_oauth_client", oauth_client)
    first, second = await asyncio.gather(
        proxy.load_refresh_token(client, token), proxy.load_refresh_token(client, token)
    )
    assert first is not None and second is not None
    if scope_case == "client_expansion":
        with pytest.raises(TokenError) as denied:
            await proxy.exchange_refresh_token(client, first, ["openid", "mcp:access"])
        assert denied.value.error == "invalid_scope"
        assert calls == 0
        assert await proxy.load_refresh_token(client, token) is not None
        return
    if upstream_failure:
        with pytest.raises(TokenError, match="Upstream refresh failed"):
            await proxy.exchange_refresh_token(client, first, requested)
        assert await proxy.load_refresh_token(client, token) is not None
        assert proxy._translate_scopes_from_idp(["mcp:access"]) == ["mcp:access"]
    task = asyncio.create_task(proxy.exchange_refresh_token(client, first, requested))
    await asyncio.wait_for(entered.wait(), timeout=2)
    # Another authorization task must not inherit the in-flight refresh limit.
    assert proxy._translate_scopes_from_idp(["openid", "mcp:access"]) == ["openid", "mcp:access"]
    concurrent = asyncio.create_task(proxy.exchange_refresh_token(client, second, requested))
    release.set()
    results = await asyncio.gather(task, concurrent, return_exceptions=True)
    successes = [value for value in results if not isinstance(value, BaseException)]
    failures = [value for value in results if isinstance(value, TokenError)]
    counts = (len(successes), len(failures))
    assert counts == (1, 1)
    assert failures[0].error == "invalid_grant"
    assert calls == (2 if upstream_failure else 1)
    issued = successes[0]
    assert issued.scope == "openid"
    assert proxy.jwt_issuer.verify_token(issued.access_token)["scope"] == "openid"
    assert proxy.jwt_issuer.verify_token(issued.refresh_token, expected_token_use="refresh")["scope"] == "openid"
    assert (await proxy.load_refresh_token(client, issued.refresh_token)).scopes == requested
    assert await proxy.load_refresh_token(client, token) is None
    assert await proxy.load_refresh_token(client, successes[0].refresh_token) is not None

    assert proxy._translate_scopes_from_idp(["openid", "profile", "mcp:access"]) == ["openid", "profile", "mcp:access"]
