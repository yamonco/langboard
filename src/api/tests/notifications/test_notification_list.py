import os
from types import SimpleNamespace
import pytest


os.environ.setdefault("PROJECT_NAME", "langboard")

from langboard_shared.domain.services.factory.NotificationService import NotificationService
from langboard_shared.helpers import InfraHelper


def test_unread_filter_and_time_range_are_applied_before_pagination(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple] = []
    user_notification = SimpleNamespace(
        get_list=lambda *args: calls.append(args) or [],
        count_unread=lambda *args: calls.append(args) or 0,
    )
    service = NotificationService(lambda *_: None, lambda *_: None, SimpleNamespace(user_notification=user_notification))
    monkeypatch.setattr(InfraHelper, "get_references", lambda *_args, **_kwargs: {})

    assert service.get_api_list(SimpleNamespace(), "7d", 2, 20, unread_only=True) == ([], False, 0)
    assert calls[0][1:] == ("7d", 2, 20, True)
    assert calls[1][1:] == ("7d",)
