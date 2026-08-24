import json
import os
from types import SimpleNamespace
import pytest


os.environ.setdefault("PROJECT_NAME", "langboard")

from langboard.mcp_tools.BotMcp import schedule_bot_cron  # noqa: E402
from langboard.routes.bots.forms import CreateBotCronTimeForm  # noqa: E402
from langboard.routes.bots.schedules.BotScheduleApi import schedule_bot_crons  # noqa: E402
from langboard_shared.ai import BotScheduleHelper  # noqa: E402
from langboard_shared.domain.models import Bot  # noqa: E402
from langboard_shared.domain.models.BotSchedule import BotScheduleRunningType  # noqa: E402
from langboard_shared.domain.services.factory.BotService import (  # noqa: E402
    BotService,
    BotServiceError,
)
from langboard_shared.helpers import BotHelper, InfraHelper  # noqa: E402


class FakeScheduleModel:
    """Identify one native schedule association in service tests."""


def test_create_schedule_returns_canonical_receipt_and_publishes_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Every adapter receives the same created Schedule receipt."""

    bot = SimpleNamespace(id=1, get_uid=lambda: "bot-1")
    target = SimpleNamespace(id=2, get_uid=lambda: "card-1")
    schedule = SimpleNamespace(api_response=lambda: {"interval_str": "0 9 * * *"})
    schedule_model = SimpleNamespace(api_response=lambda: {"uid": "schedule-1"})
    monkeypatch.setattr(BotScheduleHelper.utils, "convert_valid_interval_str", lambda value: value)
    monkeypatch.setattr(BotScheduleHelper, "get_default_status_with_dates", lambda **kwargs: ("started", None, None))
    monkeypatch.setattr(BotHelper, "get_bot_model_class", lambda kind, table: FakeScheduleModel)
    monkeypatch.setattr(
        BotHelper,
        "get_target_model_by_param",
        lambda kind, table, uid: (FakeScheduleModel, target),
    )
    monkeypatch.setattr(InfraHelper, "get_by_id_like", lambda model, value: bot if model is Bot else None)
    monkeypatch.setattr(BotScheduleHelper, "schedule", lambda *args: (schedule, schedule_model))
    monkeypatch.setattr(BotService, "_hook_project", lambda self, value: None)

    receipt = BotService.create_schedule(
        object.__new__(BotService),
        "bot-1",
        "card",
        "card-1",
        "0 9 * * *",
        BotScheduleRunningType.Infinite,
    )

    assert receipt == {
        "operation": "created",
        "schedule": {
            "interval_str": "0 9 * * *",
            "uid": "schedule-1",
            "bot_uid": "bot-1",
            "target": {"type": "card", "uid": "card-1"},
        },
        "changes": {},
    }


def test_update_schedule_rejects_invalid_interval_before_storage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """REST and MCP share one interval validation failure code."""

    monkeypatch.setattr(BotScheduleHelper.utils, "convert_valid_interval_str", lambda value: None)
    reads: list[object] = []
    monkeypatch.setattr(BotService, "get_owned_schedule", lambda *args: reads.append(args))

    with pytest.raises(BotServiceError) as error:
        BotService.update_schedule(
            object.__new__(BotService),
            "bot-1",
            "card",
            "schedule-1",
            "invalid",
        )

    assert error.value.code == "invalid_interval"
    assert reads == []


def test_delete_schedule_rejects_foreign_schedule_with_stable_code(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A missing ownership proof yields the same fail-closed service error."""

    monkeypatch.setattr(BotHelper, "get_bot_model_class", lambda kind, table: FakeScheduleModel)
    monkeypatch.setattr(BotService, "get_owned_schedule", lambda *args: None)

    with pytest.raises(BotServiceError) as error:
        BotService.delete_schedule(
            object.__new__(BotService),
            "bot-1",
            "card",
            "schedule-foreign",
        )

    assert error.value.code == "schedule_not_found"


def test_rest_and_mcp_return_the_same_schedule_receipt() -> None:
    """REST and MCP are adapters over one canonical Schedule operation."""

    receipt = {"operation": "created", "schedule": {"uid": "schedule-1"}}
    calls: list[tuple[object, ...]] = []

    def create_schedule(*args: object) -> dict[str, object]:
        calls.append(args)
        return receipt

    service = SimpleNamespace(bot=SimpleNamespace(create_schedule=create_schedule))
    form = CreateBotCronTimeForm(
        interval_str="0 9 * * *",
        target_table="card",
        target_uid="card-1",
    )

    response = schedule_bot_crons("bot-1", form, service)
    mcp_result = schedule_bot_cron(
        "bot-1",
        "card",
        "card-1",
        "0 9 * * *",
        BotScheduleRunningType.Infinite,
        None,
        None,
        "UTC",
        service,
    )

    assert json.loads(response.body) == {"receipt": receipt}
    assert mcp_result == receipt
    assert len(calls) == 2
