from typing import NoReturn
from langboard_shared.ai import BotScheduleHelper
from langboard_shared.core.types import SafeDateTime
from langboard_shared.domain.models import (
    Bot,
    CardBotSchedule,
    ProjectBotSchedule,
    ProjectColumnBotSchedule,
    ProjectRole,
    User,
)
from langboard_shared.domain.models.bases import BotTriggerCondition
from langboard_shared.domain.models.BotSchedule import BotScheduleRunningType
from langboard_shared.domain.models.ProjectRole import ProjectRoleAction
from langboard_shared.domain.services.DomainService import DomainService
from langboard_shared.domain.services.factory.BotService import BotServiceError
from langboard_shared.security import RoleFinder
from ..mcp_integration import McpRoleFilter, McpTool


@McpTool.add(description="Get bot schedules for a project.")
@McpRoleFilter.add(ProjectRole, [ProjectRoleAction.Update], RoleFinder.project)
def get_bot_schedules_by_project(bot_uid: str, project_uid: str, service: DomainService) -> dict:
    bot = service.bot.get_by_id_like(bot_uid)
    if not bot:
        raise ValueError("Bot not found")

    project = service.project.get_by_id_like(project_uid)
    if not project:
        raise ValueError("Project not found")

    schedules = BotScheduleHelper.get_all_by_scope(ProjectBotSchedule, bot, project, as_api=True)

    return {"schedules": schedules, "target": project.api_response()}


@McpTool.add(description="Get bot schedules for a card.")
@McpRoleFilter.add(ProjectRole, [ProjectRoleAction.Update], RoleFinder.project)
def get_bot_schedules_by_card(bot_uid: str, card_uid: str, service: DomainService) -> dict:
    bot = service.bot.get_by_id_like(bot_uid)
    if not bot:
        raise ValueError("Bot not found")

    card = service.card.get_by_id_like(card_uid)
    if not card:
        raise ValueError("Card not found")

    schedules = BotScheduleHelper.get_all_by_scope(CardBotSchedule, bot, card, as_api=True)

    return {"schedules": schedules, "target": card.api_response()}


@McpTool.add(description="Get bot schedules for a column.")
@McpRoleFilter.add(ProjectRole, [ProjectRoleAction.Update], RoleFinder.project)
def get_bot_schedules_by_column(bot_uid: str, column_uid: str, service: DomainService) -> dict:
    bot = service.bot.get_by_id_like(bot_uid)
    if not bot:
        raise ValueError("Bot not found")

    column = service.project_column.get_by_id_like(column_uid)
    if not column:
        raise ValueError("Column not found")

    schedules = BotScheduleHelper.get_all_by_scope(ProjectColumnBotSchedule, bot, column, as_api=True)

    return {"schedules": schedules, "target": column.api_response()}


@McpTool.add(description="Schedule a bot cron schedule.")
@McpRoleFilter.add(ProjectRole, [ProjectRoleAction.Update], RoleFinder.project)
def schedule_bot_cron(
    bot_uid: str,
    target_table: str,
    target_uid: str,
    interval_str: str,
    running_type: BotScheduleRunningType | None,
    start_at: str | SafeDateTime | None,
    end_at: str | SafeDateTime | None,
    tz: str | float | None,
    service: DomainService,
) -> dict:
    if isinstance(start_at, str):
        start_at = SafeDateTime.fromisoformat(start_at)
    if isinstance(end_at, str):
        end_at = SafeDateTime.fromisoformat(end_at)

    try:
        return service.bot.create_schedule(
            bot_uid,
            target_table,
            target_uid,
            interval_str,
            running_type,
            start_at,
            end_at,
            tz or "UTC",
        )
    except BotServiceError as error:
        _raise_bot_service_error(error)


@McpTool.add(description="Reschedule a bot cron schedule.")
@McpRoleFilter.add(ProjectRole, [ProjectRoleAction.Update], RoleFinder.project)
def reschedule_bot_cron(
    bot_uid: str,
    schedule_uid: str,
    target_table: str,
    interval_str: str | None,
    running_type: BotScheduleRunningType | None,
    start_at: str | SafeDateTime | None,
    end_at: str | SafeDateTime | None,
    tz: str | float,
    service: DomainService,
) -> dict:
    if isinstance(start_at, str):
        start_at = SafeDateTime.fromisoformat(start_at)
    if isinstance(end_at, str):
        end_at = SafeDateTime.fromisoformat(end_at)

    try:
        return service.bot.update_schedule(
            bot_uid,
            target_table,
            schedule_uid,
            interval_str,
            running_type,
            start_at,
            end_at,
            tz or "UTC",
        )
    except BotServiceError as error:
        _raise_bot_service_error(error)


@McpTool.add(description="Unschedule a bot cron schedule.")
@McpRoleFilter.add(ProjectRole, [ProjectRoleAction.Update], RoleFinder.project)
def unschedule_bot_cron(bot_uid: str, schedule_uid: str, target_table: str, service: DomainService) -> dict:
    try:
        return service.bot.delete_schedule(bot_uid, target_table, schedule_uid)
    except BotServiceError as error:
        _raise_bot_service_error(error)


def _raise_bot_service_error(error: BotServiceError) -> NoReturn:
    """Expose the same stable service error code through MCP."""

    raise ValueError(f"{error.code}: {error}") from error


@McpTool.add(description="Read one Bot-owned event Hook inside a project.")
@McpRoleFilter.add(ProjectRole, [ProjectRoleAction.Read], RoleFinder.project)
def get_bot_hook(
    project_uid: str,
    bot_uid: str,
    target_table: str,
    hook_uid: str,
    user_or_bot: User | Bot,
    service: DomainService,
) -> dict:
    """Return the same canonical Hook projection exposed by REST."""

    _ensure_bot_author(user_or_bot, bot_uid)
    try:
        hook = service.bot.get_hook(bot_uid, target_table, hook_uid, project=project_uid)
    except BotServiceError as error:
        _raise_bot_service_error(error)
    if not hook:
        raise ValueError("hook_not_found: Bot Hook not found or not owned by Bot")
    return {"hook": hook}


@McpTool.add(description="Idempotently converge one Bot event Hook inside a project.")
@McpRoleFilter.add(ProjectRole, [ProjectRoleAction.Update], RoleFinder.project)
def upsert_bot_hook(
    project_uid: str,
    bot_uid: str,
    target_table: str,
    target_uid: str,
    events: list[BotTriggerCondition],
    active: bool,
    user_or_bot: User | Bot,
    service: DomainService,
) -> dict:
    """Create or converge a Hook and return its canonical operation receipt."""

    _ensure_bot_author(user_or_bot, bot_uid)
    try:
        hook = service.bot.upsert_hook(
            bot_uid,
            target_table,
            target_uid,
            events,
            active=active,
            project=project_uid,
        )
    except BotServiceError as error:
        _raise_bot_service_error(error)
    if not hook:
        raise ValueError("hook_not_found: Bot or Hook target not found")
    return {"operation": "upserted", "hook": hook}


@McpTool.add(description="Update one Bot-owned event Hook inside a project.")
@McpRoleFilter.add(ProjectRole, [ProjectRoleAction.Update], RoleFinder.project)
def update_bot_hook(
    project_uid: str,
    bot_uid: str,
    target_table: str,
    hook_uid: str,
    events: list[BotTriggerCondition] | None,
    active: bool | None,
    user_or_bot: User | Bot,
    service: DomainService,
) -> dict:
    """Update a Hook and return its canonical operation receipt."""

    _ensure_bot_author(user_or_bot, bot_uid)
    try:
        hook = service.bot.update_hook(
            bot_uid,
            target_table,
            hook_uid,
            events=events,
            active=active,
            project=project_uid,
        )
    except BotServiceError as error:
        _raise_bot_service_error(error)
    if not hook:
        raise ValueError("hook_not_found: Bot Hook not found or not owned by Bot")
    return {"operation": "updated", "hook": hook}


@McpTool.add(description="Delete one Bot-owned event Hook inside a project.")
@McpRoleFilter.add(ProjectRole, [ProjectRoleAction.Update], RoleFinder.project)
def delete_bot_hook(
    project_uid: str,
    bot_uid: str,
    target_table: str,
    hook_uid: str,
    user_or_bot: User | Bot,
    service: DomainService,
) -> dict:
    """Delete a Hook and return its canonical operation receipt."""

    _ensure_bot_author(user_or_bot, bot_uid)
    try:
        hook = service.bot.delete_hook(bot_uid, target_table, hook_uid, project=project_uid)
    except BotServiceError as error:
        _raise_bot_service_error(error)
    if not hook:
        raise ValueError("hook_not_found: Bot Hook not found or not owned by Bot")
    return {"operation": "deleted", "hook": hook}


def _ensure_bot_author(actor: User | Bot, bot_uid: str) -> None:
    """Fail closed when one Bot attempts to author changes as another Bot."""

    if isinstance(actor, Bot) and actor.get_uid() != bot_uid:
        raise ValueError("bot_actor_mismatch: authenticated Bot cannot act as another Bot")


@McpTool.add(description="Get bot scopes for a project.")
@McpRoleFilter.add(ProjectRole, [ProjectRoleAction.Update], RoleFinder.project)
def get_project_bot_scopes(project_uid: str, service: DomainService) -> dict:
    project = service.project.get_by_id_like(project_uid)
    if not project:
        raise ValueError("Project not found")

    scopes = service.project.get_api_bot_scope_list(project)
    return {"scopes": scopes}


@McpTool.add(description="Get bot scopes for a card.")
@McpRoleFilter.add(ProjectRole, [ProjectRoleAction.Update], RoleFinder.project)
def get_card_bot_scopes(card_uid: str, service: DomainService) -> dict:
    card = service.card.get_by_id_like(card_uid)
    if not card:
        raise ValueError("Card not found")

    project = service.project.get_by_id_like(card.project_id)
    scopes = service.card.get_api_bot_scope_list(project, card)
    return {"scopes": scopes}


@McpTool.add(description="Get bot scopes for a column.")
@McpRoleFilter.add(ProjectRole, [ProjectRoleAction.Update], RoleFinder.project)
def get_column_bot_scopes(column_uid: str, service: DomainService) -> dict:
    column = service.project_column.get_by_id_like(column_uid)
    if not column:
        raise ValueError("Column not found")

    scopes = service.project_column.get_api_bot_scopes_by_project(column.project_id)

    column_scopes = [s for s in scopes if s.get("project_column_uid") == column_uid]
    return {"scopes": column_scopes}
