import os
from types import SimpleNamespace
import pytest


os.environ.setdefault("PROJECT_NAME", "langboard")

from langboard_shared.ai import BotScopeHelper
from langboard_shared.domain.models import Bot, BotSchedule
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


def test_update_hook_rejects_scope_owned_by_another_bot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A legacy scope UID cannot be used to mutate another Bot's Hook."""

    bot = SimpleNamespace(id=1)
    foreign_scope = SimpleNamespace(bot_id=2)
    monkeypatch.setattr(InfraHelper, "get_by_id_like", lambda model, value: bot)
    monkeypatch.setattr(BotHelper, "get_bot_model_class", lambda kind, table: FakeScopeModel)
    monkeypatch.setattr(BotScopeHelper, "get_by_id_like", lambda model, uid: foreign_scope)
    writes: list[object] = []
    monkeypatch.setattr(BotScopeHelper, "upsert_conditions", lambda *args, **kwargs: writes.append(args))

    result = BotService.update_hook(
        object.__new__(BotService),
        "bot-1",
        "card",
        "hook-foreign",
        active=False,
    )

    assert result is None
    assert writes == []


def test_delete_hook_removes_owned_scope_through_service(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Hook deletion reuses native storage while returning the canonical receipt."""

    bot = SimpleNamespace(id=1, get_uid=lambda: "bot-1")
    target = SimpleNamespace(id=2, get_uid=lambda: "card-1")
    scope = SimpleNamespace(
        bot_id=1,
        card_id=2,
        is_frozen=False,
        conditions=[BotTriggerCondition.CardMoved],
        get_scope_column_name=lambda: "card_id",
        get_uid=lambda: "hook-1",
    )
    monkeypatch.setattr(InfraHelper, "get_by_id_like", lambda model, value: bot)
    monkeypatch.setattr(BotHelper, "get_bot_model_class", lambda kind, table: FakeScopeModel)
    monkeypatch.setattr(BotScopeHelper, "get_by_id_like", lambda model, uid: scope)
    monkeypatch.setattr(
        BotHelper,
        "get_target_model_by_param",
        lambda kind, table, uid: (FakeScopeModel, target),
    )
    deleted: list[object] = []
    monkeypatch.setattr(BotScopeHelper, "delete", lambda model, value: deleted.append(value))
    monkeypatch.setattr(BotService, "_hook_project", lambda self, value: None)

    result = BotService.delete_hook(object.__new__(BotService), "bot-1", "card", "hook-1")

    assert result == {
        "uid": "hook-1",
        "bot_uid": "bot-1",
        "target": {"type": "card", "uid": "card-1"},
        "events": [BotTriggerCondition.CardMoved.value],
        "active": True,
    }
    assert deleted == [scope]


def test_get_owned_schedule_rejects_schedule_owned_by_another_bot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """REST and MCP schedule mutations share the same Bot ownership guard."""

    bot = SimpleNamespace(id=1)
    schedule_model = SimpleNamespace(bot_schedule_id=20)
    foreign_schedule = SimpleNamespace(bot_id=2)

    def get_by_id_like(model: object, value: object) -> object | None:
        if model is Bot:
            return bot
        if model is FakeScopeModel:
            return schedule_model
        if model is BotSchedule:
            return foreign_schedule
        return None

    monkeypatch.setattr(InfraHelper, "get_by_id_like", get_by_id_like)
    monkeypatch.setattr(BotHelper, "get_bot_model_class", lambda kind, table: FakeScopeModel)

    result = BotService.get_owned_schedule(
        object.__new__(BotService),
        "bot-1",
        "card",
        "schedule-foreign",
    )

    assert result is None
