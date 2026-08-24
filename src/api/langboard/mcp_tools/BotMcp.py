from langboard_shared.ai import BotScheduleHelper
from langboard_shared.core.types import SafeDateTime
from langboard_shared.domain.models import CardBotSchedule, ProjectBotSchedule, ProjectColumnBotSchedule, ProjectRole
from langboard_shared.domain.models.BotSchedule import BotScheduleRunningType
from langboard_shared.domain.models.ProjectRole import ProjectRoleAction
from langboard_shared.domain.services.DomainService import DomainService
from langboard_shared.helpers import BotHelper
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
    if tz is None:
        tz = "UTC"

    interval_str = BotScheduleHelper.utils.convert_valid_interval_str(interval_str)
    if not interval_str:
        raise ValueError("Invalid interval")

    if isinstance(start_at, str):
        start_at = SafeDateTime.fromisoformat(start_at)
    if isinstance(end_at, str):
        end_at = SafeDateTime.fromisoformat(end_at)

    if running_type is None:
        running_type = BotScheduleRunningType.Infinite

    if running_type == BotScheduleRunningType.Duration and not start_at:
        start_at = SafeDateTime.now()

    if not BotScheduleHelper.get_default_status_with_dates(running_type=running_type, start_at=start_at, end_at=end_at):
        raise ValueError("Invalid schedule parameters")

    result = BotHelper.get_target_model_by_param("schedule", target_table, target_uid)
    if not result:
        raise ValueError("Invalid target")
    target_model_class, target_model = result

    bot = service.bot.get_by_id_like(bot_uid)
    if not bot:
        raise ValueError("Bot not found")

    bot_schedule = BotScheduleHelper.schedule(
        target_model_class,
        bot,
        interval_str,
        target_model,
        running_type,
        start_at,
        end_at,
        tz,
    )
    if not bot_schedule:
        raise ValueError("Failed to schedule")

    return {"message": "Bot scheduled successfully"}


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
    if tz is None:
        tz = "UTC"

    if isinstance(start_at, str):
        start_at = SafeDateTime.fromisoformat(start_at)
    if isinstance(end_at, str):
        end_at = SafeDateTime.fromisoformat(end_at)

    owned_schedule = service.bot.get_owned_schedule(bot_uid, target_table, schedule_uid)
    if not owned_schedule:
        raise ValueError("Bot schedule not found or not owned by Bot")
    target_model_class, bot_schedule, _ = owned_schedule

    if interval_str:
        interval_str = BotScheduleHelper.utils.convert_valid_interval_str(interval_str)
        if not interval_str:
            raise ValueError("Invalid interval")

    if not BotScheduleHelper.get_default_status_with_dates(running_type=running_type, start_at=start_at, end_at=end_at):
        raise ValueError("Invalid schedule parameters")

    result = BotScheduleHelper.reschedule(
        target_model_class,
        bot_schedule,
        interval_str,
        running_type,
        start_at,
        end_at,
        tz,
    )
    if not result:
        raise ValueError("Failed to reschedule")

    return {"message": "Bot rescheduled successfully"}


@McpTool.add(description="Unschedule a bot cron schedule.")
@McpRoleFilter.add(ProjectRole, [ProjectRoleAction.Update], RoleFinder.project)
def unschedule_bot_cron(bot_uid: str, schedule_uid: str, target_table: str, service: DomainService) -> dict:
    owned_schedule = service.bot.get_owned_schedule(bot_uid, target_table, schedule_uid)
    if not owned_schedule:
        raise ValueError("Bot schedule not found or not owned by Bot")
    target_model_class, bot_schedule, _ = owned_schedule

    result = BotScheduleHelper.unschedule(target_model_class, bot_schedule)
    if not result:
        raise ValueError("Failed to unschedule")

    return {"message": "Bot unscheduled successfully"}


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
