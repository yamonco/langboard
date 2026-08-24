import os
from types import SimpleNamespace
import pytest


os.environ.setdefault("PROJECT_NAME", "langboard")

from langboard_shared.ai import BotScopeHelper
from langboard_shared.domain.models.bases import BotTriggerCondition
from langboard_shared.domain.services.factory.BotService import BotService
from langboard_shared.helpers import BotHelper, InfraHelper


class FakeScopeModel:
    """Expose the event contract of one native scope table."""

    @staticmethod
    def get_available_conditions() -> set[BotTriggerCondition]:
        return {BotTriggerCondition.CardMoved}

    @staticmethod
    def get_scope_column_name() -> str:
        return "card_id"


def test_upsert_hook_reuses_native_scope_and_returns_service_language(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A hook is an idempotent view over the existing bot scope storage."""

    bot = SimpleNamespace(id=1, get_uid=lambda: "bot-1")
    target = SimpleNamespace(id=2, get_uid=lambda: "card-1")
    scope = SimpleNamespace(
        is_frozen=False,
        conditions=[BotTriggerCondition.CardMoved],
        get_uid=lambda: "hook-1",
    )
    monkeypatch.setattr(InfraHelper, "get_by_id_like", lambda model, value: bot)
    monkeypatch.setattr(
        BotHelper,
        "get_target_model_by_param",
        lambda kind, table, uid: (FakeScopeModel, target),
    )
    monkeypatch.setattr(BotScopeHelper, "upsert_conditions", lambda *args, **kwargs: (scope, False))
    monkeypatch.setattr(BotScopeHelper, "get_list", lambda *args, **kwargs: [scope])
    monkeypatch.setattr(BotService, "_hook_project", lambda self, value: None)

    result = BotService.upsert_hook(
        object.__new__(BotService),
        "bot-1",
        "card",
        "card-1",
        [BotTriggerCondition.CardMoved],
    )

    assert result == {
        "uid": "hook-1",
        "bot_uid": "bot-1",
        "target": {"type": "card", "uid": "card-1"},
        "events": [BotTriggerCondition.CardMoved.value],
        "active": True,
    }


def test_upsert_hook_rejects_events_not_supported_by_target(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Reject an invalid subscription before persisting a scope."""

    bot = SimpleNamespace(id=1)
    target = SimpleNamespace(id=2)
    monkeypatch.setattr(InfraHelper, "get_by_id_like", lambda model, value: bot)
    monkeypatch.setattr(
        BotHelper,
        "get_target_model_by_param",
        lambda kind, table, uid: (FakeScopeModel, target),
    )
    writes: list[object] = []
    monkeypatch.setattr(BotScopeHelper, "upsert_conditions", lambda *args, **kwargs: writes.append(args))

    with pytest.raises(ValueError, match="not available"):
        BotService.upsert_hook(
            object.__new__(BotService),
            "bot-1",
            "card",
            "card-1",
            [BotTriggerCondition.ProjectUpdated],
        )

    assert writes == []


def test_upsert_hook_fails_closed_on_duplicate_native_scopes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Do not pick an arbitrary subscription when legacy data is ambiguous."""

    bot = SimpleNamespace(id=1)
    target = SimpleNamespace(id=2)
    scopes = [SimpleNamespace(), SimpleNamespace()]
    monkeypatch.setattr(InfraHelper, "get_by_id_like", lambda model, value: bot)
    monkeypatch.setattr(
        BotHelper,
        "get_target_model_by_param",
        lambda kind, table, uid: (FakeScopeModel, target),
    )
    monkeypatch.setattr(BotScopeHelper, "get_list", lambda *args, **kwargs: scopes)
    writes: list[object] = []
    monkeypatch.setattr(BotScopeHelper, "upsert_conditions", lambda *args, **kwargs: writes.append(args))

    with pytest.raises(ValueError, match="administrator repair"):
        BotService.upsert_hook(
            object.__new__(BotService),
            "bot-1",
            "card",
            "card-1",
            [BotTriggerCondition.CardMoved],
        )

    assert writes == []
