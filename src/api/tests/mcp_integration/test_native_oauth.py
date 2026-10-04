from types import SimpleNamespace
from unittest.mock import Mock
import pytest
from fastmcp.exceptions import AuthorizationError
from langboard.mcp_integration import OAuth
from langboard.middlewares.McpAuthMiddleware import mcp_auth_context


@pytest.mark.parametrize("authorized", [True, False])
async def test_oauth_workflow_resource_uses_domain_authorization_without_legacy_group(monkeypatch, authorized):
    from fastmcp import Client, FastMCP
    from langboard.mcp_integration.Providers import create_native_domain_provider
    from langboard.mcp_integration.Tool import McpTool

    calls = []

    async def bundle(**kwargs):
        calls.append(kwargs)
        if not authorized:
            raise AuthorizationError("Board access denied")
        return {"card": {"workflow": {"workflow_guidance": "Review first"}, "work_state": {}}}

    monkeypatch.setattr(McpTool, "get_tools", lambda: {})
    monkeypatch.setattr(McpTool, "get_tool", lambda name: {"handler": bundle} if name == "get_card_bundle" else None)
    server = FastMCP("OAuth resource fixture")
    server.add_provider(create_native_domain_provider(lambda name, handler: handler, modern_annotations=True))
    token = mcp_auth_context.set({"transport": "oauth", "user_or_bot": object()})
    try:
        async with Client(server) as client:
            if authorized:
                assert "Review first" in str(
                    await client.read_resource("langboard://projects/project/cards/card/workflow")
                )
                assert "Review first" in str(
                    await client.get_prompt("apply_card_workflow", {"project_uid": "project", "card_uid": "card"})
                )
            else:
                with pytest.raises(Exception, match="Board access denied"):
                    await client.read_resource("langboard://projects/project/cards/card/workflow")
        assert calls and calls[0] == {"project_uid": "project", "card_uid": "card", "include": []}
    finally:
        mcp_auth_context.reset(token)


def test_mounted_discovery_and_callback_urls_use_native_fastmcp_routes(monkeypatch):
    from fastmcp.server.auth.oidc_proxy import OIDCConfiguration
    from key_value.aio.stores.memory import MemoryStore
    from langboard.mcp_integration import Server
    from starlette.applications import Starlette
    from starlette.routing import Mount
    from starlette.testclient import TestClient

    monkeypatch.setattr(OAuth, "Env", settings())
    configuration = OIDCConfiguration(
        issuer="https://id.example",
        authorization_endpoint="https://id.example/authorize",
        token_endpoint="https://id.example/token",
        jwks_uri="https://id.example/jwks",
        response_types_supported=["code"],
        subject_types_supported=["public"],
        id_token_signing_alg_values_supported=["RS256"],
    )
    monkeypatch.setattr(OAuth.OIDCProxy, "get_oidc_configuration", lambda *args, **kwargs: configuration)
    provider = OAuth.create_oauth_provider(client_storage=MemoryStore())
    monkeypatch.setattr(OAuth, "create_oauth_provider", lambda: provider)
    app = Server.McpServer.get_oauth_http_app()
    root = Starlette(routes=[*Server.McpServer.oauth_discovery_routes, Mount("/mcp/oauth", app=app)])
    with TestClient(root, base_url="https://board.example") as client:
        response = client.get("/.well-known/oauth-authorization-server/mcp/oauth")
        assert response.status_code == 200
        metadata = response.json()
        assert metadata["issuer"] == "https://board.example/mcp/oauth"
        assert metadata["authorization_endpoint"] == "https://board.example/mcp/oauth/authorize"
        assert metadata["token_endpoint"] == "https://board.example/mcp/oauth/token"
        resource = client.get("/.well-known/oauth-protected-resource/mcp/oauth/stream")
        assert resource.status_code == 200
        assert resource.json()["resource"] == "https://board.example/mcp/oauth/stream"
        assert "mcp:access" in resource.json()["scopes_supported"]
        assert client.get("/mcp/oauth/auth/callback").status_code == 400
        assert client.post("/mcp/oauth/stream").status_code == 401
        registered = client.post(
            "/mcp/oauth/register",
            json={
                "client_name": "<example-client>",
                "redirect_uris": ["https://client.example/callback"],
                "grant_types": ["authorization_code", "refresh_token"],
                "response_types": ["code"],
                "token_endpoint_auth_method": "none",
                "scope": "mcp:access",
            },
        )
        assert registered.status_code == 201
        authorized = client.get(
            "/mcp/oauth/authorize",
            params={
                "client_id": registered.json()["client_id"],
                "redirect_uri": "https://client.example/callback",
                "response_type": "code",
                "scope": "mcp:access",
                "state": "fixture-client-state",
                "code_challenge": "A" * 43,
                "code_challenge_method": "S256",
            },
            follow_redirects=False,
        )
        assert authorized.status_code == 302
        consent = client.get(authorized.headers["location"])
        assert consent.status_code == 200
        assert "&lt;example-client&gt;" in consent.text
        assert "/images/favicon.ico" in consent.text
        assert 'name="csrf_token"' in consent.text
        from html import unescape

        assert "default-src 'none'" in unescape(consent.text)
        assert "Allow Access" in consent.text
        # Native consent submission must still reject a missing CSRF token.
        rejected = client.post(
            authorized.headers["location"],
            data={"submit": "true", "action": "approve"},
            follow_redirects=False,
        )
        assert rejected.status_code == 400


def settings(**changes):
    return SimpleNamespace(
        **{
            **dict(
                MCP_OAUTH_ENABLED=True,
                MCP_OAUTH_BASE_URL="https://board.example/mcp/oauth",
                MCP_OAUTH_DISCOVERY_URL="https://id.example/.well-known/openid-configuration",
                MCP_OAUTH_CLIENT_ID="example-client",
                MCP_OAUTH_CLIENT_SECRET="",
                MCP_OAUTH_SIGNING_KEY="example-test-signing-key-32-bytes-long",
                MCP_OAUTH_SCOPES="openid profile mcp:access",
                MCP_OAUTH_PROMPT="",
            ),
            **changes,
        }
    )


async def test_native_storage_preserves_registration_and_encrypts_state(monkeypatch, tmp_path):
    from fastmcp.server.auth.oauth_proxy import proxy
    from fastmcp.server.auth.oidc_proxy import OIDCConfiguration
    from mcp.shared.auth import OAuthClientInformationFull
    from pydantic import AnyUrl

    monkeypatch.setattr(OAuth, "Env", settings())
    monkeypatch.setattr(proxy.settings, "home", tmp_path)
    configuration = OIDCConfiguration(
        issuer="https://id.example",
        authorization_endpoint="https://id.example/authorize",
        token_endpoint="https://id.example/token",
        jwks_uri="https://id.example/jwks",
        response_types_supported=["code"],
        subject_types_supported=["public"],
        id_token_signing_alg_values_supported=["RS256"],
    )
    monkeypatch.setattr(OAuth.OIDCProxy, "get_oidc_configuration", lambda *args, **kwargs: configuration)
    first = OAuth.create_oauth_provider()
    client = OAuthClientInformationFull(
        client_id="persistence-test-client",
        client_name="encrypted-registration-marker",
        redirect_uris=[AnyUrl("https://client.example/callback")],
        scope="mcp:access",
    )
    await first.register_client(client)
    restored = OAuth.create_oauth_provider()
    loaded = await restored.get_client(client.client_id)
    assert loaded is not None
    assert loaded.client_name == client.client_name
    files = [path for path in tmp_path.rglob("*") if path.is_file()]
    assert files
    assert all(b"encrypted-registration-marker" not in path.read_bytes() for path in files)
    monkeypatch.setattr(OAuth, "Env", settings(MCP_OAUTH_SIGNING_KEY="rotated-example-signing-key-32-bytes-long"))
    rotated = OAuth.create_oauth_provider()
    assert await rotated.get_client(client.client_id) is None


def service_fixture():
    user = SimpleNamespace(id=1, activated_at=object(), deleted_at=None, is_admin=False)
    service = SimpleNamespace(
        identity_link=SimpleNamespace(get_user_by_provider_external_id=Mock(return_value=user)),
        close=Mock(),
    )
    return user, service


def test_provider_disabled_does_not_construct_or_fetch_discovery(monkeypatch):
    monkeypatch.setattr(OAuth, "Env", settings(MCP_OAUTH_ENABLED=False))
    factory = Mock()
    monkeypatch.setattr(OAuth, "OIDCProxy", factory)
    assert OAuth.create_oauth_provider() is None
    factory.assert_not_called()


def test_provider_uses_native_storage_and_generic_configuration(monkeypatch):
    monkeypatch.setattr(OAuth, "Env", settings())
    factory = Mock()
    monkeypatch.setattr(OAuth, "OIDCProxy", factory)
    OAuth.create_oauth_provider()
    args = factory.call_args.kwargs
    assert args["client_storage"] is None
    assert args["verify_id_token"] is True
    assert args["require_authorization_consent"] is True
    assert args["extra_authorize_params"] is None
    assert args["valid_scopes"] == ["openid", "profile", "mcp:access"]


@pytest.mark.parametrize(
    "changes",
    [
        {"MCP_OAUTH_BASE_URL": "http://board.example"},
        {"MCP_OAUTH_SIGNING_KEY": "short"},
        {"MCP_OAUTH_SCOPES": "openid profile"},
    ],
)
def test_incomplete_configuration_fails_closed(monkeypatch, changes):
    monkeypatch.setattr(OAuth, "Env", settings(**changes))
    with pytest.raises(ValueError):
        OAuth.create_oauth_provider()


@pytest.mark.parametrize("issuer", ["https://id.example", "https://id.example/"])
def test_principal_uses_issuer_subject_without_toolgroup_dependency(monkeypatch, issuer):
    monkeypatch.setattr(OAuth, "Env", settings())
    user, service = service_fixture()
    token = SimpleNamespace(claims={"iss": issuer, "sub": "stable-sub", "email": "ignored@example.invalid"})
    result = OAuth.resolve_principal(token, service)
    assert result["user_or_bot"] is user
    assert "tool_group" not in result
    assert service.identity_link.get_user_by_provider_external_id.call_args.args[1:] == (
        "stable-sub",
        "https://id.example",
    )


@pytest.mark.parametrize("change", ["inactive", "deleted", "missing_identity"])
def test_current_user_revocation_denies_existing_token(monkeypatch, change):
    monkeypatch.setattr(OAuth, "Env", settings())
    user, service = service_fixture()
    if change == "inactive":
        user.activated_at = None
    elif change == "deleted":
        user.deleted_at = object()
    else:
        service.identity_link.get_user_by_provider_external_id.return_value = None
    with pytest.raises(AuthorizationError):
        OAuth.resolve_principal(SimpleNamespace(claims={"iss": "https://id.example", "sub": "stable-sub"}), service)


async def test_request_resets_context_and_closes_service_on_handler_failure(monkeypatch):
    monkeypatch.setattr(OAuth, "Env", settings())
    user, service = service_fixture()
    monkeypatch.setattr(OAuth, "DomainService", lambda: service)
    monkeypatch.setattr(
        OAuth, "get_access_token", lambda: SimpleNamespace(claims={"iss": "https://id.example", "sub": "stable-sub"})
    )
    previous = mcp_auth_context.get()

    async def handler(_):
        assert mcp_auth_context.get()["user_or_bot"] is user
        raise RuntimeError("fixture failure")

    with pytest.raises(RuntimeError):
        await OAuth.NativeOAuthMiddleware().on_request(None, handler)
    assert mcp_auth_context.get() is previous
    service.close.assert_called_once()
