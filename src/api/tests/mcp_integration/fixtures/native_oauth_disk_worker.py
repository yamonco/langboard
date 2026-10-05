"""Separate-process native OAuth storage fixture; no production identity or secrets."""

import asyncio
import json
import sys
import time
from types import SimpleNamespace
from fastmcp.server.auth.oauth_proxy.models import JTIMapping, RefreshTokenMetadata, UpstreamTokenSet
from fastmcp.server.auth.oidc_proxy import OIDCConfiguration, OIDCProxy
from fastmcp.server.auth.providers.jwt import JWTVerifier
from joserfc import jwk, jwt
from langboard.mcp_integration import OAuth
from mcp.shared.auth import OAuthClientInformationFull


async def main():
    mode = sys.argv[1]
    configuration = OIDCConfiguration(
        issuer="https://id.example",
        authorization_endpoint="https://id.example/authorize",
        token_endpoint="https://id.example/token",
        jwks_uri="https://id.example/jwks",
        response_types_supported=["code"],
        subject_types_supported=["public"],
        id_token_signing_alg_values_supported=["HS256"],
    )
    OIDCProxy.get_oidc_configuration = lambda *args, **kwargs: configuration
    OAuth.Env = SimpleNamespace(
        MCP_OAUTH_ENABLED=True,
        MCP_OAUTH_BASE_URL="https://board.example/mcp/oauth",
        MCP_OAUTH_DISCOVERY_URL="https://id.example/.well-known/openid-configuration",
        MCP_OAUTH_CLIENT_ID="native-fixture",
        MCP_OAUTH_CLIENT_SECRET="isolated-upstream-secret",
        MCP_OAUTH_SIGNING_KEY="isolated-wrong-signing-key-at-least-32-characters"
        if mode == "wrong-key"
        else "isolated-stable-signing-key-at-least-32-characters",
        MCP_OAUTH_SCOPES="openid mcp:access",
        MCP_OAUTH_PROMPT="select_account",
    )
    provider = OAuth.create_oauth_provider()
    upstream_key = "isolated-upstream-test-key-at-least-32-characters"
    provider._token_validator = JWTVerifier(
        public_key=upstream_key, algorithm="HS256", issuer="https://id.example", audience="native-fixture"
    )
    provider.get_routes(mcp_path="/stream")
    now = time.time()
    if mode == "write":
        await provider.register_client(
            OAuthClientInformationFull(
                client_id="durable-fixture",
                redirect_uris=["http://localhost:8765/callback"],
                token_endpoint_auth_method="none",
                grant_types=["authorization_code", "refresh_token"],
                scope="openid mcp:access",
            )
        )
        claims = {
            "iss": "https://id.example",
            "aud": "native-fixture",
            "sub": "isolated-subject",
            "iat": int(now),
            "exp": int(now) + 3600,
        }
        id_token = jwt.encode({"alg": "HS256"}, claims, jwk.OctKey.import_key(upstream_key))
        await provider._upstream_token_store.put(
            key="durable-upstream",
            value=UpstreamTokenSet(
                upstream_token_id="durable-upstream",
                access_token="isolated-upstream-access-marker",
                refresh_token="isolated-upstream-refresh-marker",
                refresh_token_expires_at=now + 7200,
                expires_at=now + 3600,
                token_type="Bearer",
                scope="openid mcp:access",
                client_id="durable-fixture",
                created_at=now,
                raw_token_data={"id_token": id_token},
            ),
        )
        await provider._jti_mapping_store.put(
            key="durable-jti", value=JTIMapping(jti="durable-jti", upstream_token_id="durable-upstream", created_at=now)
        )
        await provider._refresh_token_store.put(
            key="durable-refresh-hash",
            value=RefreshTokenMetadata(
                client_id="durable-fixture", scopes=["openid", "mcp:access"], expires_at=int(now) + 7200, created_at=now
            ),
        )
    elif mode == "missing-mapping":
        await provider._jti_mapping_store.delete(key="durable-jti")
    token = provider.jwt_issuer.issue_access_token(
        client_id="durable-fixture", scopes=["openid", "mcp:access"], jti="durable-jti"
    )
    client = await provider.get_client("durable-fixture")
    upstream = await provider._upstream_token_store.get(key="durable-upstream")
    refresh = await provider._refresh_token_store.get(key="durable-refresh-hash")
    validated = await provider.load_access_token(token)
    restored = mode != "wrong-key"
    assert (client is not None) is restored
    assert (upstream is not None) is restored
    assert (refresh is not None) is restored
    assert (validated is not None) is (mode not in {"wrong-key", "missing-mapping"})
    if validated is not None:
        assert validated.claims["sub"] == "isolated-subject"
        assert set(validated.scopes) == {"openid", "mcp:access"}
    print(
        json.dumps(
            {
                "mode": mode,
                "client_restored": client is not None,
                "upstream_restored": upstream is not None,
                "refresh_metadata_restored": refresh is not None,
                "access_validated": validated is not None,
            }
        )
    )


asyncio.run(main())
