from ...ai import BotDefaultTrigger, BotScheduleHelper
from ...core.broker import Broker
from ...core.db import BaseDbModel, DbSession, SqlBuilder
from ...core.types import SafeDateTime
from ...domain.models import Bot, Card, Project, ProjectColumn
from ...domain.models.bases import BaseBotScheduleModel
from ...domain.models.BotSchedule import BotSchedule, BotScheduleRunningType, BotScheduleStatus
from ...helpers import BotHelper, ModelHelper
from ...publishers import ProjectBotPublisher
from .utils import BotTaskHelper, BotTaskSchemaHelper
from .utils.BotTaskHelper import logger


@BotTaskSchemaHelper.schema(
    BotDefaultTrigger.BotCronScheduled,
    {
        "project_uid": "string",
        "project_column_uid": "string",
        "card_uid?": "string",
        "scope": "string",
    },
)
@Broker.wrap_async_task_decorator
async def bot_cron_scheduled(bot: Bot, bot_schedule: BotSchedule, schedule_model: BaseBotScheduleModel):
    await _run_scheduler(bot, bot_schedule, schedule_model)


async def run_scheduled_bots_cron(interval_str: str):
    if interval_str.startswith("scheduled "):
        await _check_bot_schedule_runnable(interval_str.removeprefix("scheduled "))
        return

    interval_str = BotScheduleHelper.utils.convert_valid_interval_str(interval_str)
    if not interval_str:
        logger.error(f"Invalid interval string: {interval_str}")
        return

    model_classes = ModelHelper.get_models_by_base_class(BaseBotScheduleModel)
    records: list[tuple[BaseBotScheduleModel, BotSchedule, Bot]] = []
    with DbSession.use(readonly=True) as db:
        for model_class in model_classes:
            result = db.exec(
                SqlBuilder.select.tables(model_class, BotSchedule, Bot)
                .join(
                    BotSchedule,
                    model_class.column("bot_schedule_id") == BotSchedule.column("id"),
                )
                .join(Bot, BotSchedule.column("bot_id") == Bot.column("id"))
                .where(
                    (Bot.column("deleted_at").is_(None))
                    & (BotSchedule.column("interval_str") == interval_str)
                    & (BotSchedule.column("status") == BotScheduleStatus.Started)
                    & (BotSchedule.column("running_type") != BotScheduleRunningType.Onetime)
                )
            )
            records.extend(result.all())

    for schedule_model, bot_schedule, bot in records:
        await _run_scheduler(bot, bot_schedule, schedule_model)


async def _check_bot_schedule_runnable(interval_str: str):
    current_time = SafeDateTime.now()
    model_classes = ModelHelper.get_models_by_base_class(BaseBotScheduleModel)
    records: list[tuple[BaseBotScheduleModel, BotSchedule, Bot]] = []
    with DbSession.use(readonly=True) as db:
        for model_class in model_classes:
            result = db.exec(
                SqlBuilder.select.tables(model_class, BotSchedule, Bot)
                .join(
                    BotSchedule,
                    model_class.column("bot_schedule_id") == BotSchedule.column("id"),
                )
                .join(Bot, BotSchedule.column("bot_id") == Bot.column("id"))
                .where(
                    (Bot.column("deleted_at").is_(None))
                    & (BotSchedule.column("status") == BotScheduleStatus.Pending)
                    & (BotSchedule.column("start_at") <= current_time)
                    & (BotSchedule.column("interval_str") == interval_str)
                )
            )
            records.extend(result.all())

    with DbSession.use(readonly=False) as db:
        db.exec(
            SqlBuilder.update.table(BotSchedule)
            .values({"status": BotScheduleStatus.Started})
            .where(
                (BotSchedule.column("status") == BotScheduleStatus.Pending)
                & (BotSchedule.column("start_at") <= current_time)
                & (BotSchedule.column("interval_str") == interval_str)
                & (BotSchedule.column("running_type") == BotScheduleRunningType.Onetime)
            )
        )

    for schedule_model, bot_schedule, bot in records:
        if bot_schedule.running_type == BotScheduleRunningType.Duration:
            if (
                not bot_schedule.start_at
                or not bot_schedule.end_at
                or bot_schedule.start_at >= bot_schedule.end_at
                or bot_schedule.end_at < current_time
            ):
                continue

        BotScheduleHelper.change_status(
            schedule_model.__class__,
            schedule_model,
            BotScheduleStatus.Started,
            bot_schedule=bot_schedule,
        )

        model = BotHelper.get_target_model_by_bot_model("schedule", schedule_model)
        if not model:
            continue

        project = None
        if isinstance(model, ProjectColumn) or isinstance(model, Card):
            with DbSession.use(readonly=True) as db:
                result = db.exec(
                    SqlBuilder.select.table(Project).where(Project.column("id") == model.project_id).limit(1)
                )
                project = result.first()

        if project:
            ProjectBotPublisher.rescheduled(project, schedule_model, {"status": bot_schedule.status.value})

        await _run_scheduler(bot, bot_schedule, schedule_model, model)


async def _run_scheduler(
    bot: Bot, bot_schedule: BotSchedule, schedule_model: BaseBotScheduleModel, model: BaseDbModel | None = None
):
    if bot_schedule.status != BotScheduleStatus.Started:
        return

    if not model:
        model = BotHelper.get_target_model_by_bot_model("schedule", schedule_model)
        if not model:
            return

    project = None
    data = {}
    with DbSession.use(readonly=True) as db:
        if isinstance(model, ProjectColumn):
            result = db.exec(SqlBuilder.select.table(Project).where(Project.column("id") == model.project_id).limit(1))
            project = result.first()
            if not project:
                return
            data = {
                "project_column_uid": model.get_uid(),
                "project_uid": project.get_uid(),
                "scope": ProjectColumn.__tablename__,
            }
        elif isinstance(model, Card):
            result = db.exec(
                SqlBuilder.select.tables(ProjectColumn, Project)
                .join(Project, ProjectColumn.column("project_id") == Project.column("id"))
                .where(ProjectColumn.column("id") == model.project_column_id)
                .limit(1)
            )
            column, project = result.first() or (None, None)
            if not column or not project:
                return
            data = {
                "project_column_uid": column.get_uid(),
                "card_uid": model.get_uid(),
                "project_uid": project.get_uid(),
                "scope": Card.__tablename__,
            }
        else:
            return

    with DbSession.use(readonly=False) as db:
        schedule_model.last_rnu_at = SafeDateTime.now()
        db.update(schedule_model)

    await BotTaskHelper.run(bot, BotDefaultTrigger.BotCronScheduled, data, project, model)

    old_status = bot_schedule.status
    if bot_schedule.running_type == BotScheduleRunningType.Onetime:
        BotScheduleHelper.change_status(schedule_model.__class__, schedule_model, BotScheduleStatus.Stopped)
    elif bot_schedule.running_type == BotScheduleRunningType.Duration:
        if bot_schedule.end_at and bot_schedule.end_at < SafeDateTime.now():
            BotScheduleHelper.change_status(schedule_model.__class__, schedule_model, BotScheduleStatus.Stopped)

    if project and bot_schedule.status != old_status:
        ProjectBotPublisher.rescheduled(project, schedule_model, {"status": bot_schedule.status.value})
