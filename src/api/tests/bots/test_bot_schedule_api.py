"""Bot Schedule REST adapter tests."""

from collections.abc import Callable
from types import SimpleNamespace
from typing import Any
from langboard.routes.bots.forms import CreateBotCronTimeForm, DeleteBotCronTimeForm, UpdateBotCronTimeForm
from langboard.routes.bots.schedules.BotScheduleApi import (
    reschedule_bot_crons,
    schedule_bot_crons,
    unschedule_bot_crons,
)


def test_project_scoped_schedule_adapters_forward_the_authority_boundary() -> None:
    """Every canonical mutation passes its path project to the shared service."""

    calls: list[tuple[str, dict[str, Any]]] = []

    def record(operation: str) -> Callable[..., dict[str, str]]:
        def handler(*_args: object, **kwargs: Any) -> dict[str, str]:
            calls.append((operation, kwargs))
            return {"operation": operation}

        return handler

    service = SimpleNamespace(
        bot=SimpleNamespace(
            create_schedule=record("created"),
            update_schedule=record("updated"),
            delete_schedule=record("deleted"),
        )
    )

    schedule_bot_crons(
        "bot-1",
        CreateBotCronTimeForm(interval_str="0 9 * * *", target_table="card", target_uid="card-1"),
        service,
        project_uid="project-1",
    )
    reschedule_bot_crons(
        "bot-1",
        "schedule-1",
        UpdateBotCronTimeForm(target_table="card"),
        service,
        project_uid="project-1",
    )
    unschedule_bot_crons(
        "bot-1",
        "schedule-1",
        DeleteBotCronTimeForm(target_table="card"),
        service,
        project_uid="project-1",
    )

    assert calls == [
        ("created", {"project": "project-1"}),
        ("updated", {"project": "project-1"}),
        ("deleted", {"project": "project-1"}),
    ]
