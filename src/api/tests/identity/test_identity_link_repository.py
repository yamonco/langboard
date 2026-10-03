"""Exercise identity lookup SQL without replacing its authorization predicates."""

from contextlib import contextmanager
from importlib import import_module
from types import SimpleNamespace
from sqlalchemy import create_engine, text
from langboard_shared.domain.models import IdentityProvider
repository_module = import_module("langboard_shared.infrastructure.repositories.factory.UserIdentityLinkRepository")


def test_user_provider_lookup_finds_scoped_identity_and_honors_explicit_issuer(monkeypatch):
    engine = create_engine("sqlite://")
    with engine.begin() as connection:
        connection.execute(text("""
            CREATE TABLE user_identity_link (
                id INTEGER PRIMARY KEY, created_at TIMESTAMP, updated_at TIMESTAMP,
                user_id INTEGER NOT NULL, provider VARCHAR NOT NULL,
                external_id VARCHAR NOT NULL, issuer VARCHAR NOT NULL, email VARCHAR
            )
        """))
        connection.execute(text("""
            INSERT INTO user_identity_link
                (id, user_id, provider, external_id, issuer)
            VALUES (1, 42, 'oidc', 'oidc-sub', 'https://id.example'),
                   (2, 42, 'scim', 'scim-id', 'https://directory.example/scim'),
                   (3, 7, 'oidc', 'other-sub', 'https://other.example')
        """))

    @contextmanager
    def session(**kwargs):
        with engine.connect() as connection:
            yield SimpleNamespace(exec=connection.execute)

    monkeypatch.setattr(repository_module.DbSession, "use", session)
    repository = repository_module.UserIdentityLinkRepository.__new__(repository_module.UserIdentityLinkRepository)
    assert repository.get_by_user_provider(42, IdentityProvider.Oidc).external_id == "oidc-sub"
    assert repository.get_by_user_provider(42, IdentityProvider.Scim).external_id == "scim-id"
    assert repository.get_by_user_provider(42, IdentityProvider.Oidc, "https://id.example/").id == 1
    assert repository.get_by_user_provider(42, IdentityProvider.Oidc, "https://other.example") is None
    assert repository.get_by_user_provider(42, IdentityProvider.Oidc, "") is None
    assert repository.get_by_user_provider(99, IdentityProvider.Oidc) is None
    assert repository.get_by_provider_external_id(IdentityProvider.Oidc, "oidc-sub", "https://other.example") is None
    engine.dispose()
