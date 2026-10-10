"""An existing Langboard account may link OIDC only after both logins succeed."""

from __future__ import annotations
import json
import os
from types import SimpleNamespace
from typing import Any
import pytest


os.environ.setdefault("PROJECT_NAME", "langboard")

from langboard.routes.auth import OidcAuthApi  # noqa: E402
from langboard_shared.domain.models import IdentityProvider  # noqa: E402
from langboard_shared.domain.services.factory.IdentityLinkService import IdentityLinkService  # noqa: E402


def _user(user_id: int) -> Any:
    return SimpleNamespace(id=user_id, activated_at=object(), deleted_at=None, firstname="A", lastname="B")


def test_existing_account_links_only_after_its_own_langboard_and_oidc_logins(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cache: dict[str, Any] = {}
    monkeypatch.setattr(OidcAuthApi.OidcClient, "is_enabled", lambda: True)
    monkeypatch.setattr(OidcAuthApi.OidcClient, "build_authorize_url", lambda **_: "https://idp.example/authorize")
    monkeypatch.setattr(OidcAuthApi.OidcClient, "exchange_code", lambda _: {"id_token": "validated-by-mock"})
    monkeypatch.setattr(
        OidcAuthApi.OidcClient,
        "validate_id_token",
        lambda *_args, **_kwargs: {
            "sub": "immutable-subject",
            "iss": "https://idp.example/realm",
            "email": "profile@example.com",
        },
    )
    monkeypatch.setattr(OidcAuthApi.Cache, "set", lambda key, value, _ttl: cache.__setitem__(key, value))
    monkeypatch.setattr(OidcAuthApi.Cache, "get", lambda key: cache.get(key))
    monkeypatch.setattr(OidcAuthApi.Cache, "delete", lambda key: cache.pop(key, None))
    monkeypatch.setattr(OidcAuthApi.AuthSecurity, "authenticate", lambda _id: ("local-access", "local-refresh"))

    account = _user(42)
    links: list[dict[str, Any]] = []
    service = SimpleNamespace(
        user=SimpleNamespace(
            get_by_id_like=lambda user_id: account if user_id == "42" else None,
            get_by_email=lambda _email: pytest.fail("email is not an identity join"),
            update=lambda *_args: None,
        ),
        identity_link=SimpleNamespace(
            get_user_by_provider_external_id=lambda *_args: None,
            get_by_user_provider=lambda *_args: None,
            upsert_user_link=lambda **kwargs: links.append(kwargs),
        ),
    )

    started = json.loads(OidcAuthApi.oidc_link_login(user=account).body)
    state = started["state"]
    response = OidcAuthApi.oidc_callback(code="code", state=state, service=service)

    assert response.status_code == 200
    assert links[0]["user"] is account
    assert links[0]["external_id"] == "immutable-subject"
    assert links[0]["issuer"] == "https://idp.example/realm"
    assert cache == {}


def test_existing_oidc_subject_cannot_be_taken_from_another_account(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(OidcAuthApi.OidcClient, "is_enabled", lambda: True)
    monkeypatch.setattr(OidcAuthApi.OidcClient, "exchange_code", lambda _: {"id_token": "token"})
    monkeypatch.setattr(
        OidcAuthApi.OidcClient,
        "validate_id_token",
        lambda *_args, **_kwargs: {"sub": "subject", "iss": "https://idp.example", "email": "x@example.com"},
    )
    monkeypatch.setattr(OidcAuthApi.Cache, "get", lambda _key: {"nonce": "nonce", "link_user_id": "42"})
    monkeypatch.setattr(OidcAuthApi.Cache, "delete", lambda _key: None)
    service = SimpleNamespace(
        user=SimpleNamespace(get_by_id_like=lambda _id: _user(42)),
        identity_link=SimpleNamespace(get_user_by_provider_external_id=lambda *_args: _user(7)),
    )

    with pytest.raises(Exception):
        OidcAuthApi.oidc_callback(code="code", state="state", service=service)


def test_oidc_upsert_refuses_reassigning_either_account_or_subject(monkeypatch: pytest.MonkeyPatch) -> None:
    service = IdentityLinkService.__new__(IdentityLinkService)
    other_user_link = SimpleNamespace(id=1, user_id=7, external_id="subject", issuer="https://idp.example")
    monkeypatch.setattr(service, "get_by_user_provider", lambda *_args: None)
    monkeypatch.setattr(service, "get_by_provider_external_id", lambda *_args: other_user_link)

    with pytest.raises(ValueError, match="another user"):
        service.upsert_user_link(42, IdentityProvider.Oidc, "subject", "https://idp.example")

    monkeypatch.setattr(service, "get_by_user_provider", lambda *_args: other_user_link)
    monkeypatch.setattr(service, "get_by_provider_external_id", lambda *_args: None)
    with pytest.raises(ValueError, match="another OIDC identity"):
        service.upsert_user_link(42, IdentityProvider.Oidc, "different-subject", "https://idp.example")
