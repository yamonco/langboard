"""Identity proof authenticates the credential owner, never an inferred account."""

import base64
import hashlib
from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import uuid4
import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.asymmetric.rsa import generate_private_key
from fastmcp.exceptions import AuthorizationError
from jwt.algorithms import RSAAlgorithm
from langboard.mcp_tools import EmployeeIdentityMcp as proof
from langboard.middlewares.McpAuthMiddleware import mcp_auth_context
from langboard_shared.core.security import OidcClient
from langboard_shared.domain.models import Bot, User
from langboard_shared.Env import Env
from langboard_shared.helpers.MiddlewareHelper import MiddlewareHelper
from langboard_shared.security import Auth


ISSUER = "https://keycloak.example/realms/yamon"


def test_production_signer_derives_public_jwks_from_pem(monkeypatch, tmp_path):
    key = Ed25519PrivateKey.generate()
    path = tmp_path / "signer.pem"
    path.write_bytes(
        key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption())
    )
    monkeypatch.setattr(type(Env), "EMPLOYEE_IDENTITY_SIGNING_KEY_PATH", property(lambda _: str(path)))
    public = key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    jwk = proof.employee_identity_jwks()["keys"][0]
    assert jwk["x"] == base64.urlsafe_b64encode(public).rstrip(b"=").decode("ascii")
    assert jwk["kid"] == hashlib.sha256(public).hexdigest()[:32]
    restored = jwt.PyJWK.from_dict(jwk).key
    restored.verify(key.sign(b"proof-boundary"), b"proof-boundary")


@pytest.mark.parametrize("case", ["unconfigured", "missing", "malformed", "encrypted", "rsa"])
def test_production_signer_rejects_unusable_keys(monkeypatch, tmp_path, case):
    path = tmp_path / "signer.pem"
    if case == "malformed":
        path.write_bytes(b"not a PEM key")
    elif case in {"encrypted", "rsa"}:
        key = Ed25519PrivateKey.generate() if case == "encrypted" else generate_private_key(65537, 2048)
        encryption = (
            serialization.BestAvailableEncryption(b"fixture") if case == "encrypted" else serialization.NoEncryption()
        )
        path.write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, encryption))
    configured = "" if case == "unconfigured" else str(path)
    monkeypatch.setattr(type(Env), "EMPLOYEE_IDENTITY_SIGNING_KEY_PATH", property(lambda _: configured))
    with pytest.raises((RuntimeError, FileNotFoundError, ValueError, TypeError)):
        proof.employee_identity_jwks()


@pytest.mark.parametrize("case", ["oidc", "disabled", "invalid", "native", "api_key", "bot"])
def test_validate_auth_preserves_native_credentials_and_gates_oidc(monkeypatch, case):
    from langboard_shared.security import OidcMcpIdentity

    user = User.model_construct(id=123)
    bot = Bot.model_construct(id=456)
    calls = []
    claims = {"iss": ISSUER, "sub": "verified-user"}

    def resolve(token):
        calls.append(token)
        if case == "invalid":
            raise PermissionError("invalid OIDC credential")
        return user, claims

    monkeypatch.setattr(OidcMcpIdentity, "resolve_oidc_mcp_identity", resolve)
    monkeypatch.setattr(Auth, "validate", lambda _: user if case == "native" else 401)
    monkeypatch.setattr(Auth, "validate_user_by_api_key", lambda _: (user, "fixture-api-key"))
    monkeypatch.setattr(Auth, "validate_user_by_api_token", lambda _: 401)
    monkeypatch.setattr(Auth, "validate_bot", lambda _: bot)
    headers = [(b"authorization", b"Bearer fixture-token")]
    if case == "api_key":
        headers.append((b"x-api-key", b"fixture-api-key"))
    if case == "bot":
        headers.append((b"x-api-token", b"fixture-bot-token"))
    scope = {"type": "http", "headers": headers, "oidc_claims": {"sub": "stale"}}
    result = MiddlewareHelper.validate_auth(scope, allow_oidc=case != "disabled")
    if case == "oidc":
        assert result is user and scope["oidc_claims"] is claims
        assert calls == ["fixture-token"]
    elif case == "invalid":
        assert result == 401 and "oidc_claims" not in scope
        assert calls == ["fixture-token"]
    else:
        assert result is (bot if case == "bot" else user) if case != "disabled" else result == 401
        assert "oidc_claims" not in scope and not calls


def configure(monkeypatch):
    monkeypatch.setattr(type(Env), "OIDC_ISSUER", property(lambda _: ISSUER))
    monkeypatch.setattr(type(Env), "OIDC_API_AUDIENCE", property(lambda _: "langboard-api"))


@pytest.mark.parametrize(
    "case",
    [
        "valid",
        "api_key",
        "no_claims",
        "wrong_user",
        "wrong_link",
        "inactive",
        "expired",
        "wrong_audience",
        "wrong_issuer",
    ],
)
def test_identity_proof_is_scoped_and_bounded(monkeypatch, case):
    configure(monkeypatch)
    key = Ed25519PrivateKey.generate()
    monkeypatch.setattr(proof, "identity_signer", lambda: (key, "public", "test"))
    user = SimpleNamespace(id=123)
    now = int(datetime.now(timezone.utc).timestamp())
    claims = {"iss": ISSUER, "sub": "keycloak-user", "aud": "langboard-api", "exp": now + 30}
    link = SimpleNamespace(user_id=123, issuer=ISSUER, external_id="keycloak-user")
    active = SimpleNamespace(activated_at=object(), deleted_at=None)
    context = {"user_or_bot": user, "api_key": None, "oidc_claims": claims}
    if case == "api_key":
        context["api_key"] = object()
    if case == "no_claims":
        context["oidc_claims"] = None
    if case == "wrong_user":
        context["user_or_bot"] = SimpleNamespace(id=456)
    if case == "wrong_link":
        link.external_id = "other-user"
    if case == "inactive":
        active.activated_at = None
    if case == "expired":
        claims["exp"] = now - 1
    if case == "wrong_audience":
        claims["aud"] = "other-api"
    if case == "wrong_issuer":
        claims["iss"] = "https://evil.example"
    service = SimpleNamespace(
        user=SimpleNamespace(get_by_id_like=lambda _: active),
        identity_link=SimpleNamespace(get_by_user_provider=lambda *_: link),
    )
    nonce = str(uuid4())
    token = mcp_auth_context.set(context)
    try:
        if case != "valid":
            with pytest.raises(AuthorizationError):
                proof.get_employee_identity_proof(user, service, nonce)
            return
        result = proof.get_employee_identity_proof(user, service, nonce)
        decoded = jwt.decode(
            result.attestation,
            key.public_key(),
            algorithms=["EdDSA"],
            issuer=proof.PROOF_ISSUER,
            audience=proof.PROOF_AUDIENCE,
        )
        assert decoded["oidc_sub"] == "keycloak-user"
        assert decoded["sub"] == "123"
        assert decoded["request_nonce"] == nonce
        assert decoded["exp"] == claims["exp"]
        assert "email" not in decoded
    finally:
        mcp_auth_context.reset(token)


@pytest.mark.parametrize(
    "overrides", [{}, {"aud": "other-api"}, {"iss": "https://evil.example"}, {"exp": 1}, {"typ": "ID"}]
)
def test_native_oidc_access_validation_rejects_wrong_credential(monkeypatch, overrides):
    configure(monkeypatch)
    key = generate_private_key(public_exponent=65537, key_size=2048)
    monkeypatch.setattr(OidcClient, "is_enabled", lambda: True)
    monkeypatch.setattr(OidcClient, "get_discovery", lambda: {"issuer": ISSUER})
    import json

    monkeypatch.setattr(OidcClient, "_find_jwk", lambda _: json.loads(RSAAlgorithm.to_jwk(key.public_key())))
    now = int(datetime.now(timezone.utc).timestamp())
    claims = {
        "iss": ISSUER,
        "sub": "keycloak-user",
        "aud": "langboard-api",
        "exp": now + 60,
        "iat": now,
        "typ": "Bearer",
        **overrides,
    }
    token = jwt.encode(claims, key, algorithm="RS256", headers={"kid": "test"})
    if overrides:
        with pytest.raises(Exception):
            OidcClient.validate_access_token(token)
    else:
        assert OidcClient.validate_access_token(token)["sub"] == "keycloak-user"
        forged = jwt.encode(claims, generate_private_key(public_exponent=65537, key_size=2048), algorithm="RS256")
        with pytest.raises(jwt.InvalidSignatureError):
            OidcClient.validate_access_token(forged)


@pytest.mark.parametrize("case", ["valid", "issuer", "inactive", "same_account"])
def test_oidc_resolution_requires_existing_exact_account_link(monkeypatch, case):
    from langboard_shared.security import OidcMcpIdentity as identity

    claims = {"iss": ISSUER, "sub": "keycloak-user"}
    monkeypatch.setattr(OidcClient, "validate_access_token", lambda _: claims)
    user = SimpleNamespace(id=123, activated_at=object(), deleted_at=None)
    link = SimpleNamespace(user_id=123, issuer=ISSUER, external_id="keycloak-user")
    current = SimpleNamespace(issuer=ISSUER, external_id="keycloak-user")
    if case == "issuer":
        link.issuer = "https://evil.example"
    if case == "inactive":
        user.deleted_at = object()
    if case == "same_account":
        current.external_id = "another-person"
    service = SimpleNamespace(
        identity_link=SimpleNamespace(
            get_by_provider_external_id=lambda *_: link, get_by_user_provider=lambda *_: current
        ),
        user=SimpleNamespace(get_by_id_like=lambda _: user),
        close=lambda: None,
    )
    monkeypatch.setattr(identity, "DomainService", lambda: service)
    if case == "valid":
        assert identity.resolve_oidc_mcp_identity("opaque")[0] is user
    else:
        with pytest.raises(PermissionError):
            identity.resolve_oidc_mcp_identity("opaque")
