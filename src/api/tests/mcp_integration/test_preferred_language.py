import os
from types import SimpleNamespace
import pytest


os.environ.setdefault("PROJECT_NAME", "langboard")
from langboard_shared.domain.services.factory.UserService import UserService  # noqa: E402


@pytest.mark.parametrize("language", ["en-US", "ko-KR", "ja-JP", "zh-CN"])
def test_supported_language_persists(language: str) -> None:
    writes = []
    user = SimpleNamespace(preferred_lang="en-US")
    repository = SimpleNamespace(update_preferred_lang=lambda user, lang: writes.append((user, lang)))
    service = UserService(lambda *_: None, lambda *_: None, SimpleNamespace(user=repository))
    assert service.update_preferred_lang(user, language) is True
    assert user.preferred_lang == language
    assert writes == [(user, language)]


def test_unknown_language_does_not_write() -> None:
    writes = []
    user = SimpleNamespace(preferred_lang="en-US")
    repository = SimpleNamespace(update_preferred_lang=lambda user, lang: writes.append((user, lang)))
    service = UserService(lambda *_: None, lambda *_: None, SimpleNamespace(user=repository))
    assert service.update_preferred_lang(user, "unknown") is False
    assert user.preferred_lang == "en-US"
    assert writes == []


def test_bootstrap_preference_reads_primary_before_replica_replay(monkeypatch) -> None:
    from langboard_shared.core.db.DbEngine import DbEngine
    from langboard_shared.infrastructure.repositories.factory.UserRepository import UserRepository
    from sqlalchemy import create_engine, text

    primary = create_engine("sqlite://")
    replica = create_engine("sqlite://")
    for engine, language in [(primary, "ko-KR"), (replica, "en-US")]:
        with engine.begin() as connection:
            connection.execute(text('CREATE TABLE "user" (id BIGINT PRIMARY KEY, preferred_lang TEXT NOT NULL)'))
            connection.execute(text('INSERT INTO "user" VALUES (1, :language)'), {"language": language})
    monkeypatch.setattr(DbEngine, "get_main_engine", lambda: primary)
    monkeypatch.setattr(DbEngine, "get_readonly_engine", lambda: replica)
    repo = UserRepository(lambda *_: None, lambda *_: None)
    stale_actor = SimpleNamespace(id=1, preferred_lang="en-US")
    assert repo.get_preferred_lang(stale_actor) == "ko-KR"
    with replica.connect() as connection:
        assert connection.execute(text('SELECT preferred_lang FROM "user"')).scalar() == "en-US"
    primary.dispose()
    replica.dispose()


def test_restore_writes_primary_even_when_authentication_already_has_requested_language(monkeypatch) -> None:
    from langboard_shared.core.db.DbEngine import DbEngine
    from langboard_shared.infrastructure.repositories.factory.UserRepository import UserRepository
    from sqlalchemy import create_engine, text

    primary = create_engine("sqlite://")
    with primary.begin() as connection:
        connection.execute(
            text(
                'CREATE TABLE "user" (id BIGINT PRIMARY KEY, preferred_lang TEXT NOT NULL, updated_at TIMESTAMP, deleted_at TIMESTAMP)'
            )
        )
        connection.execute(text('INSERT INTO "user" (id, preferred_lang) VALUES (1, :language)'), {"language": "en-US"})
    monkeypatch.setattr(DbEngine, "get_main_engine", lambda: primary)
    repo = UserRepository(lambda *_: None, lambda *_: None)
    stale_actor = SimpleNamespace(id=1, preferred_lang="ko-KR")
    service = UserService(lambda *_: None, lambda *_: None, SimpleNamespace(user=repo))
    assert service.update_preferred_lang(stale_actor, "ko-KR") is True
    with primary.connect() as connection:
        assert connection.execute(text('SELECT preferred_lang FROM "user"')).scalar() == "ko-KR"
    primary.dispose()
