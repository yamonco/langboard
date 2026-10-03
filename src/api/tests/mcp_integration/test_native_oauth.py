from types import SimpleNamespace
from unittest.mock import Mock
import pytest
from fastmcp.exceptions import AuthorizationError
from langboard.mcp_integration import OAuth
from langboard.middlewares.McpAuthMiddleware import mcp_auth_context


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


def test_principal_uses_issuer_subject_without_toolgroup_dependency(monkeypatch):
    monkeypatch.setattr(OAuth, "Env", settings())
    user, service = service_fixture()
    token = SimpleNamespace(
        claims={"iss": "https://id.example", "sub": "stable-sub", "email": "ignored@example.invalid"}
    )
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
