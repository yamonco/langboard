"""Resolve a verified OIDC bearer to its existing, active Langboard account."""

from typing import Any
from ..core.security import OidcClient
from ..domain.models import IdentityProvider, User
from ..domain.services import DomainService


def resolve_oidc_mcp_identity(token: str) -> tuple[User, dict[str, Any]]:
    claims = OidcClient.validate_access_token(token)
    if claims.get("typ", "Bearer") != "Bearer":
        raise PermissionError("OIDC access token required")
    issuer = str(claims["iss"]).strip().rstrip("/")
    service = DomainService()
    try:
        link = service.identity_link.get_by_provider_external_id(IdentityProvider.Oidc, claims["sub"], issuer)
        if link is None or link.issuer != issuer:
            raise PermissionError("OIDC identity is not linked")
        user = service.user.get_by_id_like(link.user_id)
        if user is None or not user.activated_at or user.deleted_at is not None:
            raise PermissionError("OIDC account is inactive")
        current_link = service.identity_link.get_by_provider_external_id(IdentityProvider.Oidc, claims["sub"], issuer)
        if (
            current_link is None
            or current_link.user_id != user.id
            or current_link.external_id != claims["sub"]
            or current_link.issuer != issuer
        ):
            raise PermissionError("OIDC account identity differs")
        return user, claims
    finally:
        service.close()
