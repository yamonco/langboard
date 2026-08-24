import asyncio
import importlib
import os
from types import SimpleNamespace
import pytest


os.environ.setdefault("PROJECT_NAME", "langboard")

from langboard_shared.domain.models.bases import BotTriggerCondition  # noqa: E402
from langboard_shared.tasks.bots.utils import BotTaskHelper  # noqa: E402
from langboard_shared.tasks.webhooks import WebhookTask  # noqa: E402


bot_task_helper_module = importlib.import_module("langboard_shared.tasks.bots.utils.BotTaskHelper")


def test_bot_authored_event_is_published_but_does_not_cascade(monkeypatch: pytest.MonkeyPatch) -> None:
    """A bot action stays observable without recursively invoking scoped bots."""

    published: list[object] = []
    requests: list[object] = []
    monkeypatch.setattr(WebhookTask, "webhook_task", published.append)
    monkeypatch.setattr(bot_task_helper_module, "create_request", lambda *args, **kwargs: requests.append(args))

    asyncio.run(
        BotTaskHelper.run(
            [SimpleNamespace()],
            BotTriggerCondition.CardMoved,
            {"executor": {"uid": "bot-1", "type": "bot"}},
        )
    )

    assert len(published) == 1
    assert requests == []


def test_user_authored_event_remains_eligible_for_hooks() -> None:
    """Human board activity remains a valid Hook trigger."""

    assert BotTaskHelper.is_bot_authored_event({"executor": {"uid": "user-1", "type": "user"}}) is False
