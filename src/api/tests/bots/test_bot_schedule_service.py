import asyncio
import json
import os
from contextlib import contextmanager
from types import SimpleNamespace
from typing import Iterator
import pytest


os.environ.setdefault("PROJECT_NAME", "langboard")

from langboard.mcp_tools.BotMcp import get_bot_schedules_by_project, schedule_bot_cron  # noqa: E402
from langboard.routes.bots.forms import CreateBotCronTimeForm  # noqa: E402
from langboard.routes.bots.schedules.BotScheduleApi import schedule_bot_crons  # noqa: E402
from langboard_shared.ai import BotScheduleHelper  # noqa: E402
from langboard_shared.domain.models import Bot, Project, ProjectBotSchedule  # noqa: E402
from langboard_shared.domain.models.BotSchedule import (  # noqa: E402
    BotScheduleRunningType,
    BotScheduleStatus,
)
from langboard_shared.domain.services.factory.BotService import (  # noqa: E402
    BotService,
    BotServiceError,
)
from langboard_shared.helpers import BotHelper, InfraHelper  # noqa: E402
from langboard_shared.tasks.bots import BotScheduleTask  # noqa: E402


class FakeScheduleModel:
    """Identify one native schedule association in service tests."""


def test_project_schedule_executes_with_project_context(monkeypatch: pytest.MonkeyPatch) -> None:
    """A project-targeted schedule reaches the bot instead of being silently discarded."""

    class FakeProject:
        __tablename__ = "project"

        @staticmethod
        def get_uid() -> str:
            return "project-1"

    class FakeDb:
        @staticmethod
        def update(_record: object) -> None:
            return None

    @contextmanager
    def use_db(*, readonly: bool) -> Iterator[FakeDb]:
        assert readonly is False
        yield FakeDb()

    calls: list[tuple[object, ...]] = []

    async def run_bot(*args: object, **_kwargs: object) -> None:
        calls.append(args)

    monkeypatch.setattr(BotScheduleTask, "Project", FakeProject)
    monkeypatch.setattr(BotScheduleTask.DbSession, "use", use_db)
    monkeypatch.setattr(BotScheduleTask.BotTaskHelper, "run", run_bot)

    bot = SimpleNamespace()
    schedule = SimpleNamespace(
        status=BotScheduleStatus.Started,
        running_type=BotScheduleRunningType.Infinite,
    )
    schedule_model = SimpleNamespace(last_rnu_at=None)
    project = FakeProject()

    asyncio.run(BotScheduleTask._run_scheduler(bot, schedule, schedule_model, project))

    assert len(calls) == 1
    assert calls[0][0:2] == (bot, BotScheduleTask.BotDefaultTrigger.BotCronScheduled)
    assert calls[0][2] == {"project_uid": "project-1", "scope": "project"}
    assert calls[0][3:] == (project, project)


def test_started_schedules_are_loaded_in_bounded_batches(monkeypatch: pytest.MonkeyPatch) -> None:
    """Cron processing releases each query batch before running its bots."""

    records = [(SimpleNamespace(id=index), SimpleNamespace(), SimpleNamespace()) for index in range(1, 4)]
    batches = [records[:2], records[2:]]
    read_count = 0

    class FakeResult:
        def __init__(self, rows: list[tuple[object, object, object]]) -> None:
            self.rows = rows

        def all(self) -> list[tuple[object, object, object]]:
            return self.rows

    class FakeDb:
        def exec(self, _query: object) -> FakeResult:
            nonlocal read_count
            rows = batches[read_count]
            read_count += 1
            return FakeResult(rows)

    @contextmanager
    def use_db(*, readonly: bool) -> Iterator[FakeDb]:
        assert readonly is True
        yield FakeDb()

    processed: list[int] = []

    async def run_schedule(_bot: object, _schedule: object, schedule_model: object) -> None:
        processed.append(schedule_model.id)

    monkeypatch.setattr(BotScheduleTask, "BOT_SCHEDULE_BATCH_SIZE", 2)
    monkeypatch.setattr(BotScheduleTask.DbSession, "use", use_db)
    monkeypatch.setattr(BotScheduleTask, "_run_scheduler", run_schedule)

    asyncio.run(BotScheduleTask._run_started_schedules(ProjectBotSchedule, "0 9 * * *"))

    assert processed == [1, 2, 3]
    assert read_count == 2


def test_pending_project_schedule_publishes_started_status(monkeypatch: pytest.MonkeyPatch) -> None:
    """Project schedules publish the same start transition as card and column schedules."""

    class FakeProject:
        pass

    project = FakeProject()
    schedule_model = SimpleNamespace()
    schedule = SimpleNamespace(
        status=BotScheduleStatus.Pending,
        running_type=BotScheduleRunningType.Reserved,
    )
    published: list[tuple[object, object, dict[str, str]]] = []
    executed: list[object] = []

    def change_status(
        _model_class: type[object],
        _model: object,
        status: BotScheduleStatus,
        **_kwargs: object,
    ) -> object:
        schedule.status = status
        return schedule

    async def run_schedule(_bot: object, _schedule: object, _schedule_model: object, model: object) -> None:
        executed.append(model)

    monkeypatch.setattr(BotScheduleTask, "Project", FakeProject)
    monkeypatch.setattr(
        BotScheduleTask,
        "_claim_pending_schedule",
        lambda schedule_model, bot_schedule: bool(
            change_status(type(schedule_model), schedule_model, BotScheduleStatus.Started, bot_schedule=bot_schedule)
        ),
    )
    monkeypatch.setattr(BotScheduleTask.BotScheduleHelper, "change_status", change_status)
    monkeypatch.setattr(BotScheduleTask.BotHelper, "get_target_model_by_bot_model", lambda *_args: project)
    monkeypatch.setattr(BotScheduleTask.ProjectBotPublisher, "rescheduled", lambda *args: published.append(args))
    monkeypatch.setattr(BotScheduleTask, "_run_scheduler", run_schedule)

    asyncio.run(
        BotScheduleTask._run_pending_schedule(
            schedule_model,
            schedule,
            SimpleNamespace(),
            BotScheduleTask.SafeDateTime.now(),
        )
    )

    assert published == [(project, schedule_model, {"status": BotScheduleStatus.Started.value})]
    assert executed == [project]


def test_pending_schedule_is_not_executed_when_another_worker_claims_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    schedule = SimpleNamespace(
        status=BotScheduleStatus.Pending,
        running_type=BotScheduleRunningType.Reserved,
    )
    executed: list[object] = []
    claims: list[object] = []

    def reject_claim(*args: object) -> bool:
        claims.append(args)
        return False

    monkeypatch.setattr(BotScheduleTask.BotHelper, "get_target_model_by_bot_model", lambda *_args: object())
    monkeypatch.setattr(BotScheduleTask, "_claim_pending_schedule", reject_claim)
    monkeypatch.setattr(
        BotScheduleTask,
        "_run_scheduler",
        lambda *_args: executed.append(_args),
    )

    asyncio.run(
        BotScheduleTask._run_pending_schedule(
            SimpleNamespace(),
            schedule,
            SimpleNamespace(),
            BotScheduleTask.SafeDateTime.now(),
        )
    )

    assert len(claims) == 1
    assert executed == []


def test_pending_schedule_without_target_is_not_claimed(monkeypatch: pytest.MonkeyPatch) -> None:
    schedule = SimpleNamespace(
        status=BotScheduleStatus.Pending,
        running_type=BotScheduleRunningType.Reserved,
    )
    claims: list[object] = []

    monkeypatch.setattr(BotScheduleTask.BotHelper, "get_target_model_by_bot_model", lambda *_args: None)
    monkeypatch.setattr(BotScheduleTask, "_claim_pending_schedule", lambda *args: claims.append(args))

    asyncio.run(
        BotScheduleTask._run_pending_schedule(
            SimpleNamespace(),
            schedule,
            SimpleNamespace(),
            BotScheduleTask.SafeDateTime.now(),
        )
    )

    assert claims == []


def test_pending_schedule_claim_uses_a_conditional_status_update(monkeypatch: pytest.MonkeyPatch) -> None:
    updates: list[object] = []
    status_changes: list[object] = []

    class FakeDb:
        def exec(self, statement: object) -> int:
            updates.append(statement)
            return 0

    @contextmanager
    def use_db(*, readonly: bool) -> Iterator[FakeDb]:
        assert readonly is False
        yield FakeDb()

    monkeypatch.setattr(BotScheduleTask.DbSession, "use", use_db)
    monkeypatch.setattr(
        BotScheduleTask.BotScheduleHelper,
        "change_status",
        lambda *_args, **_kwargs: status_changes.append((_args, _kwargs)),
    )

    claimed = BotScheduleTask._claim_pending_schedule(
        SimpleNamespace(),
        SimpleNamespace(id=1, status=BotScheduleStatus.Pending),
    )

    assert claimed is False
    assert len(updates) == 1
    assert "bot_schedule.status" in str(updates[0].whereclause)
    assert status_changes == []


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
    calls: list[tuple[tuple[object, ...], dict[str, object]]] = []

    def create_schedule(*args: object, **kwargs: object) -> dict[str, object]:
        calls.append((args, kwargs))
        return receipt

    service = SimpleNamespace(bot=SimpleNamespace(create_schedule=create_schedule))
    form = CreateBotCronTimeForm(
        interval_str="0 9 * * *",
        target_table="card",
        target_uid="card-1",
    )

    response = schedule_bot_crons("bot-1", form, service)
    mcp_result = schedule_bot_cron(
        "project-1",
        "bot-1",
        "card",
        "card-1",
        "0 9 * * *",
        BotScheduleRunningType.Infinite,
        None,
        None,
        "UTC",
        SimpleNamespace(),
        service,
    )

    assert json.loads(response.body) == {"receipt": receipt}
    assert mcp_result == receipt
    assert len(calls) == 2
    assert calls[0][1] == {}
    assert calls[1][1] == {"project": "project-1"}


def test_mcp_schedule_list_uses_bounded_pagination(monkeypatch: pytest.MonkeyPatch) -> None:
    """MCP list reads must not materialize every schedule for a long-lived project."""

    captured: list[object] = []
    bot = SimpleNamespace()
    project = SimpleNamespace(api_response=lambda: {"uid": "project-1"})
    service = SimpleNamespace(
        bot=SimpleNamespace(get_by_id_like=lambda _uid: bot),
        project=SimpleNamespace(get_by_id_like=lambda _uid: project),
    )

    def get_schedules(*_args: object, **kwargs: object) -> list[object]:
        captured.append(kwargs["pagination"])
        return []

    monkeypatch.setattr(BotScheduleHelper, "get_all_by_scope", get_schedules)

    result = get_bot_schedules_by_project(
        "bot-1",
        "project-1",
        SimpleNamespace(),
        service,
        limit=100,
        page=2,
    )

    assert result == {"schedules": [], "target": {"uid": "project-1"}}
    assert captured[0].limit == 100
    assert captured[0].page == 2

    with pytest.raises(ValueError):
        get_bot_schedules_by_project(
            "bot-1",
            "project-1",
            SimpleNamespace(),
            service,
            limit=101,
        )


def test_create_schedule_rejects_target_outside_authorized_project(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A valid target UID cannot bypass the caller's authorized project."""

    target = SimpleNamespace(id=2, project_id=3, get_uid=lambda: "card-1")
    authorized_project = SimpleNamespace(id=4)
    target_project = SimpleNamespace(id=3)
    bot = SimpleNamespace(id=1)
    monkeypatch.setattr(BotScheduleHelper.utils, "convert_valid_interval_str", lambda value: value)
    monkeypatch.setattr(BotScheduleHelper, "get_default_status_with_dates", lambda **kwargs: ("started", None, None))
    monkeypatch.setattr(BotHelper, "get_bot_model_class", lambda kind, table: FakeScheduleModel)
    monkeypatch.setattr(BotHelper, "get_target_model_by_param", lambda kind, table, uid: (FakeScheduleModel, target))

    def resolve(model: object, value: object) -> object | None:
        if model is Bot:
            return bot
        if model is Project:
            return authorized_project if value == "project-1" else target_project
        return None

    monkeypatch.setattr(InfraHelper, "get_by_id_like", resolve)

    with pytest.raises(BotServiceError) as error:
        BotService.create_schedule(
            object.__new__(BotService),
            "bot-1",
            "card",
            "card-1",
            "0 9 * * *",
            project="project-1",
        )

    assert error.value.code == "project_mismatch"
