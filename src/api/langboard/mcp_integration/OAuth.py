"""Optional native OAuth using FastMCP and existing Langboard identity policy."""

import logging
from urllib.parse import urlsplit
from uuid import uuid4
import anyio
from fastmcp.exceptions import AuthorizationError
from fastmcp.server.auth.oidc_proxy import OIDCProxy
from fastmcp.server.dependencies import get_access_token
from fastmcp.server.middleware import Middleware
from langboard_shared.domain.models import IdentityProvider
from langboard_shared.domain.services import DomainService
from langboard_shared.Env import Env
from mcp.server.auth.provider import RefreshToken, TokenError
from mcp.shared.auth import OAuthClientInformationFull, OAuthToken
from ..middlewares.McpAuthMiddleware import mcp_auth_context


class LangboardOIDCProxy(OIDCProxy):
    """Keep upstream scopes within the MCP client's verified consent grant."""

    async def exchange_refresh_token(
        self, client: OAuthClientInformationFull, refresh_token: RefreshToken, scopes: list[str]
    ) -> OAuthToken:
        if not hasattr(self, "_exchange_lock"):
            # ponytail: serialize one provider process; shared atomic claims required before replica scaling.
            self._exchange_lock = anyio.Lock()
        async with self._exchange_lock:
            current = await self.load_refresh_token(client, refresh_token.token)
            if current is None:
                raise TokenError("invalid_grant", "Refresh token was already consumed or expired")
            return await super().exchange_refresh_token(client, current, scopes)

    async def storage_readiness(self, *, timeout=3):
        """Probe the existing encrypted store without touching client credentials."""
        if not hasattr(self, "_readiness_lock"):
            self._readiness_lock = anyio.Lock()
        result = {"component": "oauth_storage", "status": "ready"}
        key = str(uuid4())
        collection = "langboard_oauth_readiness"
        payload = {"probe": key}
        try:
            with anyio.fail_after(timeout):
                async with self._readiness_lock:
                    try:
                        await self._client_storage.put(key, payload, collection=collection, ttl=60)
                        if await self._client_storage.get(key, collection=collection) != payload:
                            result.update(status="not_ready", reason="round_trip_mismatch")
                    finally:
                        await self._client_storage.delete(key, collection=collection)
        except TimeoutError:
            result.update(status="not_ready", reason="storage_timeout")
        except OSError:
            result.update(status="not_ready", reason="storage_io_error")
        except Exception:
            result.update(status="not_ready", reason="storage_error")
        state = result.get("reason", "ready")
        if getattr(self, "_readiness_state", None) != state:
            logging.getLogger(__name__).log(
                logging.INFO if state == "ready" else logging.WARNING,
                "Native MCP OAuth storage readiness: %s",
                state,
            )
            self._readiness_state = state
        return result

    async def load_access_token(self, token: str):
        validated = await super().load_access_token(token)
        if validated is None:
            return None
        try:
            granted = self.jwt_issuer.verify_token(token).get("scope", "")
        except Exception:
            return None
        if not isinstance(granted, str):
            return None
        allowed = set(granted.split())
        return validated.model_copy(update={"scopes": [scope for scope in validated.scopes if scope in allowed]})


def create_oauth_provider(*, client_storage=None):
    """Keep provider choice and persistent storage under operator control."""
    if not Env.MCP_OAUTH_ENABLED:
        return None
    for value in (Env.MCP_OAUTH_BASE_URL, Env.MCP_OAUTH_DISCOVERY_URL):
        parsed = urlsplit(value)
        if parsed.scheme != "https" or not parsed.netloc or parsed.username or parsed.password:
            raise ValueError("Native MCP OAuth requires HTTPS public and discovery URLs")
    if not Env.MCP_OAUTH_CLIENT_ID or len(Env.MCP_OAUTH_SIGNING_KEY) < 32:
        raise ValueError("Native MCP OAuth requires a client and stable signing key")
    if "mcp:access" not in Env.MCP_OAUTH_SCOPES.split():
        raise ValueError("Native MCP OAuth scopes must include mcp:access")
    return LangboardOIDCProxy(
        config_url=Env.MCP_OAUTH_DISCOVERY_URL,
        client_id=Env.MCP_OAUTH_CLIENT_ID,
        client_secret=Env.MCP_OAUTH_CLIENT_SECRET or None,
        base_url=Env.MCP_OAUTH_BASE_URL,
        jwt_signing_key=Env.MCP_OAUTH_SIGNING_KEY,
        verify_id_token=True,
        valid_scopes=Env.MCP_OAUTH_SCOPES.split(),
        extra_authorize_params={"prompt": Env.MCP_OAUTH_PROMPT} if Env.MCP_OAUTH_PROMPT else None,
        require_authorization_consent=True,
        client_storage=client_storage,
    )


def resolve_principal(access_token, service):
    """Resolve verified OIDC claims; never infer identity from names or email."""
    claims = access_token.claims if access_token else None
    issuer = claims.get("iss") if isinstance(claims, dict) else None
    subject = claims.get("sub") if isinstance(claims, dict) else None
    if not isinstance(issuer, str) or not issuer or not isinstance(subject, str) or not subject:
        raise AuthorizationError("A verified OIDC identity is required")
    issuer = issuer.strip().rstrip("/")
    if not issuer:
        raise AuthorizationError("A verified OIDC identity is required")
    user = service.identity_link.get_user_by_provider_external_id(
        IdentityProvider.Oidc, subject, issuer, consistent=True
    )
    if not user or not user.activated_at or user.deleted_at:
        raise AuthorizationError("An active linked user is required")
    return {"user_or_bot": user, "api_key": None, "transport": "oauth"}


class NativeOAuthMiddleware(Middleware):
    """Refresh linked-user status on each authenticated MCP request."""

    async def on_request(self, context, call_next):
        service = DomainService()
        try:
            principal = resolve_principal(get_access_token(), service)
        finally:
            service.close()
        token = mcp_auth_context.set(principal)
        try:
            return await call_next(context)
        finally:
            mcp_auth_context.reset(token)
