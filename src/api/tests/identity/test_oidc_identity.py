"""OIDC issuer-subject identity and resource-token tests."""

from __future__ import annotations
import importlib.util
import os
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from uuid import uuid4
import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations
from cryptography.hazmat.primitives.asymmetric import ec
from jwt import encode as jwt_encode
from jwt.algorithms import ECAlgorithm
from starlette.datastructures import Headers


os.environ.setdefault("PROJECT_NAME", "langboard")

from langboard_shared.core.caching import Cache  # noqa: E402
from langboard_shared.core.security import AuthSecurity, DelegatedOidcClient, OidcClient  # noqa: E402
from langboard_shared.domain.models import IdentityProvider  # noqa: E402
from langboard_shared.domain.services.factory.IdentityLinkService import IdentityLinkService  # noqa: E402
from langboard_shared.Env import Env  # noqa: E402
from langboard_shared.helpers import (
    InfraHelper,  # noqa: E402
    MiddlewareHelper,  # noqa: E402
)
from langboard_shared.security import Auth  # noqa: E402


ROOT = Path(__file__).resolve().parents[4]
MIGRATION = ROOT / "src/api/langboard/migrations/versions/20260903235000-6f4a9d18c2e1.py"
MULTI_ISSUER_MIGRATION = ROOT / "src/api/langboard/migrations/versions/20260909173000-a3d9f6c27b41.py"


def test_access_token_requires_the_configured_resource_audience(monkeypatch: pytest.MonkeyPatch) -> None:
    """A token for the login client cannot be replayed against Langboard APIs."""

    Env.update_env("OIDC_BEARER_ENABLED", "true")
    Env.update_env("OIDC_RESOURCE_AUDIENCE", "langboard-api")
    Env.update_env("OIDC_CLIENT_SECRET", "test-secret")
    Env.update_env("OIDC_CLOCK_SKEW_SEC", "0")
    monkeypatch.setattr(OidcClient, "get_discovery", lambda: {"issuer": "https://issuer.example"})
    payload = {
        "sub": "employee-1",
        "iss": "https://issuer.example",
        "aud": "langboard-api",
        "iat": 1_788_400_000,
        "exp": 1_888_400_000,
    }
    valid = jwt_encode(payload, "test-secret", algorithm="HS256")
    wrong_audience = jwt_encode({**payload, "aud": "another-api"}, "test-secret", algorithm="HS256")

    assert OidcClient.validate_access_token(valid)["sub"] == "employee-1"
    with pytest.raises(Exception):
        OidcClient.validate_access_token(wrong_audience)


def test_bearer_identity_is_resolved_by_normalized_issuer_and_subject(monkeypatch: pytest.MonkeyPatch) -> None:
    """Email is profile metadata, not the durable bearer-authentication key."""

    Env.update_env("OIDC_BEARER_ENABLED", "true")
    validated_tokens: list[str] = []
    monkeypatch.setattr(
        OidcClient,
        "validate_access_token",
        lambda token: validated_tokens.append(token)
        or {"iss": "https://issuer.example/", "sub": "employee-1", "email": "changed@example.com"},
    )
    calls: list[tuple[Any, ...]] = []
    user = SimpleNamespace(activated_at=object(), deleted_at=None)
    service = SimpleNamespace(
        identity_link=SimpleNamespace(
            get_user_by_provider_external_id=lambda *args: calls.append(args) or user,
        ),
        close=lambda: None,
    )
    services_module = __import__("langboard_shared.domain.services", fromlist=["DomainService"])
    monkeypatch.setattr(services_module, "DomainService", lambda: service)

    result = MiddlewareHelper._validate_oidc_user(Headers({"Authorization": "Bearer   upstream-token  "}))

    assert result is user
    assert validated_tokens == ["upstream-token"]
    assert calls[0][1:] == ("employee-1", "https://issuer.example")


def test_oidc_bearer_is_disabled_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    """Deployments opt in before external tokens reach OIDC validation."""

    Env.update_env("OIDC_BEARER_ENABLED", "false")
    monkeypatch.setattr(OidcClient, "validate_access_token", lambda _token: pytest.fail("must not validate"))

    assert MiddlewareHelper._validate_oidc_user(Headers({"Authorization": "Bearer token"})) is None


def test_delegated_assertion_uses_linked_user_and_keeps_gateway_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    """The proxy credential authenticates transport but never becomes the actor."""

    Env.update_env("OIDC_DELEGATED_BEARER_ENABLED", "true")
    gateway_user = SimpleNamespace(id="gateway")
    delegated_user = SimpleNamespace(id="employee")
    api_key = SimpleNamespace(id="gateway-key")
    monkeypatch.setattr(Auth, "validate_user_by_api_key", lambda _headers: (gateway_user, api_key))
    monkeypatch.setattr(
        MiddlewareHelper,
        "_validate_delegated_oidc_token",
        lambda token: delegated_user if token == "signed.jwt" else None,
    )
    scope: dict[str, Any] = {
        "type": "http",
        "headers": [
            (AuthSecurity.API_KEY_HEADER.lower().encode(), b"gateway-secret"),
            (AuthSecurity.MCP_USER_ASSERTION_HEADER.lower().encode(), b"signed.jwt"),
        ],
    }

    assert MiddlewareHelper.validate_auth(scope) is delegated_user
    assert scope["auth"] is delegated_user
    assert scope["api_key"] is api_key


@pytest.mark.parametrize("enabled,with_api_key", [(False, True), (True, False)])
def test_delegated_assertion_fails_closed_without_both_gates(
    monkeypatch: pytest.MonkeyPatch,
    enabled: bool,
    with_api_key: bool,
) -> None:
    """A rejected assertion cannot silently fall back to the gateway owner."""

    Env.update_env("OIDC_DELEGATED_BEARER_ENABLED", str(enabled).lower())
    monkeypatch.setattr(Auth, "validate_user_by_api_key", lambda _headers: pytest.fail("must not authenticate gateway"))
    headers = [(AuthSecurity.MCP_USER_ASSERTION_HEADER.lower().encode(), b"signed.jwt")]
    if with_api_key:
        headers.append((AuthSecurity.API_KEY_HEADER.lower().encode(), b"gateway-secret"))
    scope: dict[str, Any] = {"type": "http", "headers": headers}

    assert MiddlewareHelper.validate_auth(scope) == 401
    assert "auth" not in scope


def test_unlinked_delegated_assertion_never_falls_back_to_gateway_user(monkeypatch: pytest.MonkeyPatch) -> None:
    """A valid proxy credential cannot authorize an unknown external subject."""

    Env.update_env("OIDC_DELEGATED_BEARER_ENABLED", "true")
    gateway_user = SimpleNamespace(id="gateway")
    monkeypatch.setattr(Auth, "validate_user_by_api_key", lambda _headers: (gateway_user, SimpleNamespace()))
    monkeypatch.setattr(MiddlewareHelper, "_validate_delegated_oidc_token", lambda _token: None)
    scope: dict[str, Any] = {
        "type": "http",
        "headers": [
            (AuthSecurity.API_KEY_HEADER.lower().encode(), b"gateway-secret"),
            (AuthSecurity.MCP_USER_ASSERTION_HEADER.lower().encode(), b"unknown.jwt"),
        ],
    }

    assert MiddlewareHelper.validate_auth(scope) == 401
    assert "auth" not in scope


def test_identity_migration_keys_subjects_by_provider_issuer_and_external_id() -> None:
    """Two issuers may safely use the same opaque subject value."""

    source = MIGRATION.read_text(encoding="utf-8")

    assert 'down_revision: str | None = "91f7b2c4d8e6"' in source
    assert "uq_user_identity_link_provider_issuer_external_id" in source
    assert '["provider", "issuer", "external_id"]' in source


def test_identity_migration_allows_multiple_oidc_issuers_per_user() -> None:
    source = MULTI_ISSUER_MIGRATION.read_text(encoding="utf-8")

    assert 'down_revision: str | None = "6f4a9d18c2e1"' in source
    assert "uq_user_identity_link_user_provider_issuer" in source
    assert '["user_id", "provider", "issuer"]' in source


def test_multi_issuer_migration_enforces_the_new_database_boundary() -> None:
    spec = importlib.util.spec_from_file_location("multi_issuer_identity", MULTI_ISSUER_MIGRATION)
    assert spec and spec.loader
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    metadata = sa.MetaData()
    identity_link = sa.Table(
        "user_identity_link",
        metadata,
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("provider", sa.String(), nullable=False),
        sa.Column("issuer", sa.String(), nullable=False),
        sa.Column("external_id", sa.String(), nullable=False),
        sa.UniqueConstraint("user_id", "provider", name="uq_user_identity_link_user_provider"),
        sa.UniqueConstraint(
            "provider",
            "issuer",
            "external_id",
            name="uq_user_identity_link_provider_issuer_external_id",
        ),
    )
    engine = sa.create_engine("sqlite://")
    with engine.begin() as connection:
        metadata.create_all(connection)
        connection.execute(
            identity_link.insert().values(
                id=1,
                user_id=41,
                provider="oidc",
                issuer="https://issuer-one.example",
                external_id="subject-one",
            )
        )
        migration.op = Operations(MigrationContext.configure(connection))
        migration.upgrade()
        reflected = sa.Table("user_identity_link", sa.MetaData(), autoload_with=connection)
        connection.execute(
            reflected.insert().values(
                id=2,
                user_id=41,
                provider="oidc",
                issuer="https://issuer-two.example",
                external_id="subject-two",
            )
        )
        with pytest.raises(sa.exc.IntegrityError):
            connection.execute(
                reflected.insert().values(
                    id=3,
                    user_id=41,
                    provider="oidc",
                    issuer="https://issuer-two.example",
                    external_id="subject-three",
                )
            )


def _configure_delegated_policy(monkeypatch: pytest.MonkeyPatch) -> tuple[Any, str]:
    private_key = ec.generate_private_key(ec.SECP256R1())
    public_jwk = ECAlgorithm.to_jwk(private_key.public_key(), as_dict=True)
    public_jwk.update({"kid": "test-key", "alg": "ES256", "use": "sig"})
    Env.update_env("OIDC_DELEGATED_ISSUER", "https://identity.example/delegation")
    Env.update_env("OIDC_DELEGATED_JWKS_URL", "https://identity.example/delegation/jwks.json")
    Env.update_env("OIDC_DELEGATED_AUDIENCE", "langboard-api")
    Env.update_env("OIDC_DELEGATED_ACTOR_SUBJECTS", "system:serviceaccount:apps:gateway")
    Env.update_env("OIDC_DELEGATED_MAX_TTL_SEC", "120")
    Env.update_env("OIDC_DELEGATED_CLOCK_SKEW_SEC", "30")
    monkeypatch.setattr(DelegatedOidcClient, "get_jwks", lambda: {"keys": [public_jwk]})
    return private_key, str(uuid4())


def _delegated_assertion(private_key: Any, jti: str, **overrides: Any) -> str:
    now = int(datetime.now(UTC).timestamp())
    claims = {
        "iss": "https://identity.example/delegation",
        "sub": "opaque-employee-subject",
        "aud": "langboard-api",
        "iat": now,
        "nbf": now,
        "exp": now + 120,
        "jti": jti,
        "act": {"sub": "system:serviceaccount:apps:gateway"},
        **overrides,
    }
    return jwt_encode(claims, private_key, algorithm="ES256", headers={"typ": "JWT", "kid": "test-key"})


def test_delegated_assertion_requires_trusted_actor_and_is_one_time(monkeypatch: pytest.MonkeyPatch) -> None:
    private_key, jti = _configure_delegated_policy(monkeypatch)
    seen: set[str] = set()
    monkeypatch.setattr(Cache, "set_if_absent", lambda key, _value, _ttl: False if key in seen else not seen.add(key))
    assertion = _delegated_assertion(private_key, jti)

    assert DelegatedOidcClient.validate(assertion)["sub"] == "opaque-employee-subject"
    with pytest.raises(RuntimeError, match="already used"):
        DelegatedOidcClient.validate(assertion)


@pytest.mark.parametrize(
    "override",
    [
        {"act": {"sub": "system:serviceaccount:apps:unknown"}},
        {"aud": ["langboard-api"]},
    ],
)
def test_delegated_assertion_rejects_untrusted_actor_and_non_exact_audience(
    monkeypatch: pytest.MonkeyPatch,
    override: dict[str, Any],
) -> None:
    private_key, jti = _configure_delegated_policy(monkeypatch)
    monkeypatch.setattr(Cache, "set_if_absent", lambda *_args: True)

    with pytest.raises(Exception):
        DelegatedOidcClient.validate(_delegated_assertion(private_key, jti, **override))


def test_delegated_assertion_rejects_excessive_lifetime_before_consuming_jti(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    private_key, jti = _configure_delegated_policy(monkeypatch)
    consumed: list[str] = []
    monkeypatch.setattr(Cache, "set_if_absent", lambda key, *_args: consumed.append(key) or True)
    now = int(datetime.now(UTC).timestamp())

    with pytest.raises(RuntimeError, match="lifetime"):
        DelegatedOidcClient.validate(_delegated_assertion(private_key, jti, iat=now, nbf=now, exp=now + 121))
    assert consumed == []


def test_identity_upsert_is_scoped_to_the_exact_issuer(monkeypatch: pytest.MonkeyPatch) -> None:
    current_link = SimpleNamespace(
        id=1,
        user_id=41,
        provider=IdentityProvider.Oidc,
        external_id="old-subject",
        issuer="https://issuer-two.example",
        email=None,
    )
    lookups: list[tuple[Any, ...]] = []
    updates: list[Any] = []
    identity_repo = SimpleNamespace(
        get_by_user_provider=lambda *args: lookups.append(args) or current_link,
        get_by_provider_external_id=lambda *_args: None,
        update=lambda link: updates.append(link),
    )
    repository = SimpleNamespace(user_identity_link=identity_repo)
    monkeypatch.setattr(InfraHelper, "convert_id", lambda _user: 41)
    service = IdentityLinkService(lambda *_args: None, lambda *_args: None, repository)

    result = service.upsert_user_link(
        41,
        IdentityProvider.Oidc,
        "new-subject",
        "https://issuer-two.example/",
        "profile@example.com",
    )

    assert lookups == [(41, IdentityProvider.Oidc, "https://issuer-two.example")]
    assert result is current_link
    assert result.external_id == "new-subject"
    assert updates == [current_link]


def test_identity_upsert_never_reassigns_an_external_identity(monkeypatch: pytest.MonkeyPatch) -> None:
    external_link = SimpleNamespace(id=2, user_id=99)
    identity_repo = SimpleNamespace(
        get_by_user_provider=lambda *_args: None,
        get_by_provider_external_id=lambda *_args: external_link,
        update=lambda _link: pytest.fail("must not steal an external identity"),
    )
    repository = SimpleNamespace(user_identity_link=identity_repo)
    monkeypatch.setattr(InfraHelper, "convert_id", lambda _user: 41)
    service = IdentityLinkService(lambda *_args: None, lambda *_args: None, repository)

    with pytest.raises(ValueError, match="another user"):
        service.upsert_user_link(
            41,
            IdentityProvider.Oidc,
            "owned-subject",
            "https://issuer.example",
        )
