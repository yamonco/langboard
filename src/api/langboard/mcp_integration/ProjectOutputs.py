"""Native project detail contracts preserve initialization and member variants."""

from datetime import datetime
from typing import Literal
from pydantic import Field
from .Outputs import CommandOutput
from .WorkOutputs import ProjectionOutput


class NativeMemberOutput(ProjectionOutput):
    uid: str
    created_at: datetime | str | None = None
    updated_at: datetime | str | None = None
    firstname: str
    lastname: str
    email: str
    username: str
    avatar: str | None
    type: Literal["user", "unknown", "group_email"]


class GlobalDisplayOutput(CommandOutput):
    emoji: str
    translations: dict[str, dict[str, str]]


class NativeProjectLabelOutput(CommandOutput):
    uid: str
    created_at: datetime | str | None
    updated_at: datetime | str | None
    project_uid: str
    global_label_uid: str | None
    global_display: GlobalDisplayOutput | None
    name: str
    color: str
    description: str
    order: int = Field(ge=0)


class NativeProjectOutput(ProjectionOutput):
    uid: str
    created_at: datetime | str | None
    updated_at: datetime | str | None
    owner_uid: str
    organization_uid: str | None
    title: str
    description: str | None
    ai_description: str | None
    project_type: str
    archive_visible_days: int
    dock_revision: int = Field(ge=0)
    all_members: list[NativeMemberOutput]
    invited_member_uids: list[str]
    current_auth_role_actions: list[str] | None = None
    labels: list[NativeProjectLabelOutput]


class NativeProjectBotScopeOutput(CommandOutput):
    uid: str
    created_at: datetime | str | None
    updated_at: datetime | str | None
    bot_uid: str
    default_scope_branch_uid: str | None
    conditions: list[str]
    is_frozen: bool
    project_uid: str


class NativeProjectBotScheduleOutput(CommandOutput):
    uid: str
    created_at: datetime | str | None
    updated_at: datetime | str | None
    bot_uid: str
    running_type: Literal["infinite", "duration", "reserved", "onetime"]
    status: Literal["pending", "started", "stopped"]
    interval_str: str
    start_at: datetime | str | None
    end_at: datetime | str | None
    project_uid: str


class ProjectDetailsOutput(CommandOutput):
    project: NativeProjectOutput
    project_bot_scopes: list[NativeProjectBotScopeOutput]
    project_bot_schedules: list[NativeProjectBotScheduleOutput]


PROJECT_OUTPUTS = {"get_project": ProjectDetailsOutput}
