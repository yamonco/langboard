"""OIDC issuer-subject identity and resource-token tests."""

from __future__ import annotations
import os
from pathlib import Path
from types import SimpleNamespace
from typing import Any
import pytest
from jwt import encode as jwt_encode
from starlette.datastructures import Headers


os.environ.setdefault("PROJECT_NAME", "langboard")

from langboard_shared.core.security import OidcClient  # noqa: E402
from langboard_shared.Env import Env  # noqa: E402
from langboard_shared.helpers import MiddlewareHelper  # noqa: E402


ROOT = Path(__file__).resolve().parents[4]
MIGRATION = ROOT / "src/api/langboard/migrations/versions/20260903235000-6f4a9d18c2e1.py"


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


def test_identity_migration_keys_subjects_by_provider_issuer_and_external_id() -> None:
    """Two issuers may safely use the same opaque subject value."""

    source = MIGRATION.read_text(encoding="utf-8")

    assert 'down_revision: str | None = "91f7b2c4d8e6"' in source
    assert "uq_user_identity_link_provider_issuer_external_id" in source
    assert '["provider", "issuer", "external_id"]' in source
