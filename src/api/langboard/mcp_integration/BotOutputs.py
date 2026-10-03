"""Typed native bot operation results, without changing execution authority."""

from datetime import datetime
from typing import Literal
from .Outputs import CommandOutput
from .WorkOutputs import ProjectionOutput


class BotTargetOutput(CommandOutput):
    type: str
    uid: str


class HookOutput(CommandOutput):
    uid: str
    bot_uid: str
    target: BotTargetOutput
    events: list[str]
    active: bool


class HookUpsertOutput(CommandOutput):
    operation: Literal["upserted"]
    hook: HookOutput


class HookUpdateOutput(CommandOutput):
    operation: Literal["updated"]
    hook: HookOutput


class HookDeleteOutput(CommandOutput):
    operation: Literal["deleted"]
    hook: HookOutput


class ScheduleChangesOutput(ProjectionOutput):
    running_type: Literal["infinite", "duration", "reserved", "onetime"] | None = None
    status: Literal["pending", "started", "stopped"] | None = None
    interval_str: str | None = None
    start_at: datetime | str | None = None
    end_at: datetime | str | None = None


class ScheduleOutput(CommandOutput):
    uid: str
    created_at: datetime | str | None
    updated_at: datetime | str | None
    bot_uid: str
    running_type: Literal["infinite", "duration", "reserved", "onetime"]
    status: Literal["pending", "started", "stopped"]
    interval_str: str
    start_at: datetime | str | None
    end_at: datetime | str | None
    target: BotTargetOutput


class CardScheduleOutput(ScheduleOutput):
    card_uid: str


class ProjectScheduleOutput(ScheduleOutput):
    project_uid: str


class ColumnScheduleOutput(ScheduleOutput):
    project_column_uid: str


class ScheduleMutationOutput(CommandOutput):
    schedule: CardScheduleOutput | ProjectScheduleOutput | ColumnScheduleOutput
    changes: ScheduleChangesOutput


class ScheduleCreationOutput(ScheduleMutationOutput):
    operation: Literal["created"]


class ScheduleUpdateOutput(ScheduleMutationOutput):
    operation: Literal["updated"]


class ScheduleDeleteOutput(ScheduleMutationOutput):
    operation: Literal["deleted"]


BOT_OUTPUTS = {
    "schedule_bot_cron": ScheduleCreationOutput,
    "reschedule_bot_cron": ScheduleUpdateOutput,
    "unschedule_bot_cron": ScheduleDeleteOutput,
    "upsert_bot_hook": HookUpsertOutput,
    "update_bot_hook": HookUpdateOutput,
    "delete_bot_hook": HookDeleteOutput,
}
