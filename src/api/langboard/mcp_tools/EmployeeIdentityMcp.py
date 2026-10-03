"""Short-lived, user-only identity proof for ERP's independent person check."""

import base64
import hashlib
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID, uuid4
import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastmcp.exceptions import AuthorizationError
from langboard_shared.domain.models import IdentityProvider, User
from langboard_shared.domain.services import DomainService
from langboard_shared.Env import Env
from pydantic import BaseModel
from ..mcp_integration import McpTool
from ..middlewares.McpAuthMiddleware import mcp_auth_context


PROOF_ISSUER = "urn:yam:langboard"
PROOF_AUDIENCE = "urn:yam:erp-employee-proof"


class EmployeeIdentityProof(BaseModel):
    attestation: str
    issuer: str
    audience: str
    expires_at: int
    request_nonce: str


def identity_signer() -> tuple[Ed25519PrivateKey, str, str]:
    """Read only the configured dedicated signing key; expose public coordinates."""
    path = Env.EMPLOYEE_IDENTITY_SIGNING_KEY_PATH
    if not path:
        raise RuntimeError("Employee identity signer unavailable")
    key = serialization.load_pem_private_key(Path(path).read_bytes(), password=None)
    if not isinstance(key, Ed25519PrivateKey):
        raise RuntimeError("Employee identity signer must use Ed25519")
    public = key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    x = base64.urlsafe_b64encode(public).rstrip(b"=").decode("ascii")
    kid = hashlib.sha256(public).hexdigest()[:32]
    return key, x, kid


def employee_identity_jwks() -> dict:
    _, x, kid = identity_signer()
    return {"keys": [{"kty": "OKP", "crv": "Ed25519", "use": "sig", "alg": "EdDSA", "kid": kid, "x": x}]}


@McpTool.add(
    "user",
    description="Attest the verified credential owner's OIDC identity for ERP; nonce must match the actor proof jti.",
)
def get_employee_identity_proof(user: User, service: DomainService, request_nonce: str) -> EmployeeIdentityProof:
    """Bind current verified bearer identity to a bounded ERP proof request."""
    try:
        valid_nonce = isinstance(request_nonce, str) and str(UUID(request_nonce)) == request_nonce
    except (ValueError, TypeError):
        valid_nonce = False
    if not valid_nonce:
        raise AuthorizationError("Canonical request nonce required")
    context = mcp_auth_context.get() or {}
    claims = context.get("oidc_claims")
    if context.get("api_key") is not None or not isinstance(claims, dict) or context.get("user_or_bot") is not user:
        raise AuthorizationError("Verified user OIDC bearer required")
    current = service.user.get_by_id_like(user.id)
    link = service.identity_link.get_by_user_provider(user, IdentityProvider.Oidc)
    now = int(datetime.now(timezone.utc).timestamp())
    audiences = claims.get("aud")
    if (
        current is None
        or not current.activated_at
        or current.deleted_at is not None
        or link is None
        or link.user_id != user.id
        or link.issuer != claims.get("iss")
        or link.external_id != claims.get("sub")
        or claims.get("iss") != Env.OIDC_ISSUER
        or not Env.OIDC_API_AUDIENCE
        or not (
            audiences == Env.OIDC_API_AUDIENCE or isinstance(audiences, list) and Env.OIDC_API_AUDIENCE in audiences
        )
        or type(claims.get("exp")) is not int
        or claims["exp"] <= now
    ):
        raise AuthorizationError("Current OIDC account identity unavailable")
    key, _, kid = identity_signer()
    expires = min(now + 60, claims["exp"])
    payload = {
        "iss": PROOF_ISSUER,
        "aud": PROOF_AUDIENCE,
        "sub": str(user.id),
        "oidc_iss": claims["iss"],
        "oidc_sub": claims["sub"],
        "oidc_aud": Env.OIDC_API_AUDIENCE,
        "request_nonce": request_nonce,
        "iat": now,
        "nbf": now,
        "exp": expires,
        "jti": str(uuid4()),
    }
    return EmployeeIdentityProof(
        attestation=jwt.encode(payload, key, algorithm="EdDSA", headers={"kid": kid}),
        issuer=PROOF_ISSUER,
        audience=PROOF_AUDIENCE,
        expires_at=expires,
        request_nonce=request_nonce,
    )
