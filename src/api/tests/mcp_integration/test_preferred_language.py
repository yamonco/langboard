import os
from types import SimpleNamespace
import pytest


os.environ.setdefault("PROJECT_NAME", "langboard")
from langboard_shared.domain.services.factory.UserService import UserService  # noqa: E402


@pytest.mark.parametrize("language", ["en-US", "ko-KR", "ja-JP", "zh-CN"])
def test_supported_language_persists(language: str) -> None:
    writes = []
    user = SimpleNamespace(preferred_lang="en-US")
    service = UserService(lambda *_: None, lambda *_: None, SimpleNamespace(user=SimpleNamespace(update=writes.append)))
    assert service.update_preferred_lang(user, language) is True
    assert user.preferred_lang == language
    assert writes == [user]


def test_unknown_language_does_not_write() -> None:
    writes = []
    user = SimpleNamespace(preferred_lang="en-US")
    service = UserService(lambda *_: None, lambda *_: None, SimpleNamespace(user=SimpleNamespace(update=writes.append)))
    assert service.update_preferred_lang(user, "unknown") is False
    assert user.preferred_lang == "en-US"
    assert writes == []
