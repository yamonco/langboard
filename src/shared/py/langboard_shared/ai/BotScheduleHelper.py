from typing import Any, Literal, TypeVar, cast, overload
from crontab import CronTab
from sqlalchemy import tuple_
from ..core.db import BaseDbModel, DbSession, SqlBuilder
from ..core.schema import TimeBasedPagination
from ..core.types import SafeDateTime, SnowflakeID
from ..core.utils.CronTabUtils import CronTabUtils
from ..core.utils.decorators import staticclass
from ..domain.models import Bot, BotSchedule
from ..domain.models.bases import BaseBotScheduleModel
from ..domain.models.BotSchedule import BotScheduleRunningType, BotScheduleStatus
from ..helpers import InfraHelper


_TBotScheduleModel = TypeVar("_TBotScheduleModel", bound=BaseBotScheduleModel)
_TBaseParam = int | str | None


@staticclass
class BotScheduleHelper:
    utils = CronTabUtils()

    @staticmethod
    def get_by_id_like(
        model_cls: type[_TBotScheduleModel], model: _TBotScheduleModel | _TBaseParam | None
    ) -> _TBotScheduleModel | None:
        record = InfraHelper.get_by_id_like(model_cls, model)
        return record

    @overload
    @staticmethod
    def get_all_by_scope(
        schedule_model_class: type[_TBotScheduleModel],
        bot: Bot | None,
        scope_model: BaseDbModel | list[BaseDbModel] | tuple[type[BaseDbModel], int | list[int]],
        as_api: Literal[False],
        pagination: TimeBasedPagination | None = None,
        status: BotScheduleStatus | None = None,
    ) -> list[tuple[_TBotScheduleModel, BotSchedule]]: ...
    @overload
    @staticmethod
    def get_all_by_scope(
        schedule_model_class: type[_TBotScheduleModel],
        bot: Bot | None,
        scope_model: BaseDbModel | list[BaseDbModel] | tuple[type[BaseDbModel], int | list[int]],
        as_api: Literal[True],
        pagination: TimeBasedPagination | None = None,
        status: BotScheduleStatus | None = None,
    ) -> list[dict[str, Any]]: ...
    @staticmethod
    def get_all_by_scope(
        schedule_model_class: type[_TBotScheduleModel],
        bot: Bot | None,
        scope_model: BaseDbModel | list[BaseDbModel] | tuple[type[BaseDbModel], int | list[int]],
        as_api: bool,
        pagination: TimeBasedPagination | None = None,
        status: BotScheduleStatus | None = None,
    ) -> list[tuple[_TBotScheduleModel, BotSchedule]] | list[dict[str, Any]]:
        query = SqlBuilder.select.tables(schedule_model_class, BotSchedule).join(
            BotSchedule,
            BotSchedule.column("id") == schedule_model_class.column("bot_schedule_id"),
        )

        if isinstance(scope_model, list):
            query = query.where(
                schedule_model_class.column(f"{scope_model[0].__tablename__}_id").in_([s.id for s in scope_model])
            )
        elif isinstance(scope_model, tuple):
            scope_model_class, scope_model_id = scope_model
            if isinstance(scope_model_id, list):
                query = query.where(
                    schedule_model_class.column(f"{scope_model_class.__tablename__}_id").in_(scope_model_id)
                )
            else:
                query = query.where(
                    schedule_model_class.column(f"{scope_model_class.__tablename__}_id") == scope_model_id
                )
        else:
            query = query.where(schedule_model_class.column(f"{scope_model.__tablename__}_id") == scope_model.id)

        if bot:
            query = query.where(BotSchedule.column("bot_id") == bot.id)

        if status:
            query = query.where(BotSchedule.column("status") == status)

        if pagination:
            query = query.where(BotSchedule.column("created_at") <= pagination.refer_time)
            query = query.order_by(BotSchedule.column("created_at").desc(), BotSchedule.column("id").desc())
            query = query.limit(pagination.limit).offset((pagination.page - 1) * pagination.limit)

        schedules = []
        with DbSession.use(readonly=True) as db:
            result = db.exec(query)
            schedules = result.all()

        if not as_api:
            return schedules

        api_schedules = []
        for schedule_model, schedule in schedules:
            api_schedule = {
                **schedule.api_response(),
                **schedule_model.api_response(),
            }
            api_schedules.append(api_schedule)

        return api_schedules

    @staticmethod
    def get_default_status_with_dates(
        running_type: BotScheduleRunningType | None,
        start_at: SafeDateTime | None,
        end_at: SafeDateTime | None,
    ) -> tuple[BotScheduleStatus, SafeDateTime | None, SafeDateTime | None] | None:
        if not running_type or running_type == BotScheduleRunningType.Infinite:
            return BotScheduleStatus.Started, None, None

        if BotSchedule.RUNNING_TYPES_WITH_START_AT.count(running_type) > 0 and not start_at:
            return None

        if BotSchedule.RUNNING_TYPES_WITH_END_AT.count(running_type) > 0:
            if not end_at:
                return None

            if start_at and end_at < start_at:
                return None
        else:
            end_at = None

        return BotScheduleStatus.Pending, start_at, end_at

    @staticmethod
    def schedule(
        schedule_model_class: type[_TBotScheduleModel],
        bot: Bot,
        interval_str: str,
        target_model: BaseDbModel,
        running_type: BotScheduleRunningType | None = None,
        start_at: SafeDateTime | None = None,
        end_at: SafeDateTime | None = None,
        tz: str | float = "UTC",
    ) -> tuple[BotSchedule, _TBotScheduleModel] | None:
        interval_str = BotScheduleHelper.utils.convert_valid_interval_str(interval_str)
        if not interval_str:
            return None

        interval_str = BotScheduleHelper.utils.adjust_interval_for_utc(interval_str, tz)

        if not running_type:
            running_type = BotScheduleRunningType.Infinite

        cron = BotScheduleHelper.utils.get_cron()

        has_changed = BotScheduleHelper.__create_job(cron, interval_str, running_type)

        result = BotScheduleHelper.get_default_status_with_dates(
            running_type=running_type, start_at=start_at, end_at=end_at
        )
        if not result:
            return None
        status, start_at, end_at = result

        bot_schedule = BotSchedule(
            bot_id=bot.id,
            running_type=running_type,
            status=status,
            interval_str=interval_str,
            start_at=start_at,
            end_at=end_at,
        )

        with DbSession.use(readonly=False) as db:
            db.insert(bot_schedule)

        params: dict[str, Any] = {
            "bot_schedule_id": bot_schedule.id,
            f"{target_model.__tablename__}_id": target_model.id,
        }

        schedule_model = schedule_model_class(**params)

        with DbSession.use(readonly=False) as db:
            db.insert(schedule_model)

        if has_changed:
            BotScheduleHelper.utils.save_cron(cron)

        return bot_schedule, schedule_model

    @staticmethod
    def reschedule(
        schedule_model_class: type[_TBotScheduleModel],
        schedule_model: _TBotScheduleModel | _TBaseParam,
        interval_str: str | None = None,
        running_type: BotScheduleRunningType | None = None,
        start_at: SafeDateTime | None = None,
        end_at: SafeDateTime | None = None,
        tz: str | float = "UTC",
    ) -> tuple[BotSchedule, _TBotScheduleModel, dict[str, Any]] | None:
        schedule_model = InfraHelper.get_by_id_like(schedule_model_class, schedule_model)
        if not schedule_model:
            return None

        bot_schedule = InfraHelper.get_by_id_like(BotSchedule, schedule_model.bot_schedule_id)
        if not bot_schedule:
            return None

        model = {}
        has_changed = False
        old_status = bot_schedule.status
        old_interval_str = bot_schedule.interval_str

        cron = None
        if running_type:
            if bot_schedule.running_type != running_type:
                result = BotScheduleHelper.get_default_status_with_dates(
                    running_type=running_type, start_at=start_at, end_at=end_at
                )
                if not result:
                    return None
                status, start_at, end_at = result
                bot_schedule.running_type = running_type
                bot_schedule.status = status
                bot_schedule.start_at = start_at
                bot_schedule.end_at = end_at
                model["running_type"] = running_type.value
                model["status"] = status.value
                model["start_at"] = start_at
                model["end_at"] = end_at

                cron, has_changed = BotScheduleHelper.change_status(
                    schedule_model_class,
                    schedule_model,
                    status,
                    no_update=True,
                    bot_schedule=bot_schedule,
                )
            else:
                if bot_schedule.start_at != start_at or bot_schedule.end_at != end_at:
                    result = BotScheduleHelper.get_default_status_with_dates(
                        running_type=running_type, start_at=start_at, end_at=end_at
                    )
                    if result:
                        status, _, _ = result
                        bot_schedule.status = status
                        model["status"] = status.value

                if BotSchedule.RUNNING_TYPES_WITH_START_AT.count(running_type) > 0 and start_at:
                    bot_schedule.start_at = start_at
                    model["start_at"] = start_at
                if BotSchedule.RUNNING_TYPES_WITH_END_AT.count(running_type) > 0 and end_at:
                    bot_schedule.end_at = end_at
                    model["end_at"] = end_at

        if interval_str:
            interval_str = BotScheduleHelper.utils.convert_valid_interval_str(interval_str)
            interval_str = BotScheduleHelper.utils.adjust_interval_for_utc(interval_str, tz)

            if old_interval_str != interval_str:
                bot_schedule.interval_str = interval_str
                model["interval_str"] = interval_str

                if not cron:
                    cron = BotScheduleHelper.utils.get_cron()

                if (
                    bot_schedule.running_type in BotSchedule.RUNNING_TYPES_WITH_START_AT
                    and bot_schedule.status == BotScheduleStatus.Pending
                ):
                    has_changed = BotScheduleHelper.__create_job(cron, interval_str, running_type) or has_changed
                else:
                    has_changed = BotScheduleHelper.__create_job(cron, interval_str) or has_changed

        with DbSession.use(readonly=False) as db:
            db.update(bot_schedule)

        has_old_intervals = BotScheduleHelper.__has_interval_schedule(old_interval_str, old_status)
        if not has_old_intervals:
            if not cron:
                cron = BotScheduleHelper.utils.get_cron()
            BotScheduleHelper.__remove_job(cron, old_status, old_interval_str)

        if cron and (has_changed or not has_old_intervals):
            BotScheduleHelper.utils.save_cron(cron)

        return bot_schedule, schedule_model, model

    @staticmethod
    def unschedule(
        schedule_model_class: type[_TBotScheduleModel],
        schedule_model: _TBotScheduleModel | _TBaseParam,
    ) -> tuple[BotSchedule, _TBotScheduleModel] | None:
        schedule_model = InfraHelper.get_by_id_like(schedule_model_class, schedule_model)
        if not schedule_model:
            return None

        bot_schedule = InfraHelper.get_by_id_like(BotSchedule, schedule_model.bot_schedule_id)
        if not bot_schedule:
            return None

        cron = BotScheduleHelper.utils.get_cron()

        status = bot_schedule.status
        interval_str = bot_schedule.interval_str
        with DbSession.use(readonly=False) as db:
            db.delete(bot_schedule)

        has_interval = BotScheduleHelper.__has_interval_schedule(interval_str, status)
        if not has_interval:
            BotScheduleHelper.__remove_job(cron, status, interval_str)
            BotScheduleHelper.utils.save_cron(cron)
        return bot_schedule, schedule_model

    @staticmethod
    def unschedule_by_scope(schedule_model_class: type[_TBotScheduleModel], scope_model: BaseDbModel) -> None:
        old_schedules: list[tuple[SnowflakeID, str, BotScheduleStatus]] = []
        with DbSession.use(readonly=True) as db:
            query = (
                SqlBuilder.select.columns(BotSchedule.id, BotSchedule.interval_str, BotSchedule.status)
                .join(
                    schedule_model_class,
                    BotSchedule.column("id") == schedule_model_class.column("bot_schedule_id"),
                )
                .where(schedule_model_class.column(f"{scope_model.__tablename__}_id") == scope_model.id)
            )
            result = db.exec(query)
            old_schedules = cast(Any, result.all())

        with DbSession.use(readonly=False) as db:
            db.exec(
                SqlBuilder.delete.table(BotSchedule).where(
                    BotSchedule.column("id").in_([old_schedule[0] for old_schedule in old_schedules])
                )
            )

        cron = BotScheduleHelper.utils.get_cron()
        schedule_id_has_schedules = BotScheduleHelper.__has_interval_schedule(
            [(old_schedule[1], old_schedule[2]) for old_schedule in old_schedules]
        )
        schedule_id_has_schedules = set(schedule_id_has_schedules)

        for old_schedule_id, old_interval_str, old_status in old_schedules:
            if old_schedule_id not in schedule_id_has_schedules:
                BotScheduleHelper.__remove_job(cron, old_status, old_interval_str)

        BotScheduleHelper.utils.save_cron(cron)

    @overload
    @staticmethod
    def change_status(
        schedule_model_class: type[_TBotScheduleModel],
        schedule_model: _TBotScheduleModel | _TBaseParam,
        status: BotScheduleStatus,
        no_update: None = None,
        bot_schedule: BotSchedule | None = None,
    ) -> BotSchedule | None: ...
    @overload
    @staticmethod
    def change_status(
        schedule_model_class: type[_TBotScheduleModel],
        schedule_model: _TBotScheduleModel | _TBaseParam,
        status: BotScheduleStatus,
        no_update: Literal[False],
        bot_schedule: BotSchedule | None = None,
    ) -> BotSchedule | None: ...
    @overload
    @staticmethod
    def change_status(
        schedule_model_class: type[_TBotScheduleModel],
        schedule_model: _TBotScheduleModel | _TBaseParam,
        status: BotScheduleStatus,
        no_update: Literal[True],
        bot_schedule: BotSchedule | None = None,
    ) -> tuple[CronTab, bool]: ...
    @staticmethod
    def change_status(
        schedule_model_class: type[_TBotScheduleModel],
        schedule_model: _TBotScheduleModel | _TBaseParam,
        status: BotScheduleStatus,
        no_update: bool | None = None,
        bot_schedule: BotSchedule | None = None,
    ) -> BotSchedule | tuple[CronTab, bool] | None:
        schedule_model = InfraHelper.get_by_id_like(schedule_model_class, schedule_model)
        cron = BotScheduleHelper.utils.get_cron()
        if not schedule_model:
            return None if not no_update else (cron, False)

        if not bot_schedule:
            bot_schedule = InfraHelper.get_by_id_like(BotSchedule, schedule_model.bot_schedule_id)
            if not bot_schedule:
                return None if not no_update else (cron, False)

        old_status = bot_schedule.status
        bot_schedule.status = status
        if not no_update:
            with DbSession.use(readonly=False) as db:
                db.update(bot_schedule)

        has_changed = False
        has_old_intervals = True
        old_comment = bot_schedule.interval_str
        if old_status == BotScheduleStatus.Pending and status == BotScheduleStatus.Started:
            has_changed = BotScheduleHelper.__create_job(cron, bot_schedule.interval_str)
            has_old_intervals = BotScheduleHelper.__has_interval_schedule(bot_schedule.interval_str, old_status)
            old_comment = f"scheduled {bot_schedule.interval_str}"
        elif old_status == BotScheduleStatus.Started and status == BotScheduleStatus.Pending:
            has_changed = BotScheduleHelper.__create_job(cron, bot_schedule.interval_str, bot_schedule.running_type)
            has_old_intervals = BotScheduleHelper.__has_interval_schedule(bot_schedule.interval_str, old_status)
        elif old_status == BotScheduleStatus.Started and status == BotScheduleStatus.Stopped:
            has_old_intervals = BotScheduleHelper.__has_interval_schedule(bot_schedule.interval_str, old_status)
        elif old_status == BotScheduleStatus.Stopped and status == BotScheduleStatus.Started:
            has_changed = BotScheduleHelper.__create_job(cron, bot_schedule.interval_str)
        elif old_status == BotScheduleStatus.Pending and status == BotScheduleStatus.Stopped:
            has_old_intervals = BotScheduleHelper.__has_interval_schedule(bot_schedule.interval_str, old_status)
            old_comment = f"scheduled {bot_schedule.interval_str}"
        elif old_status == BotScheduleStatus.Stopped and status == BotScheduleStatus.Pending:
            has_changed = BotScheduleHelper.__create_job(cron, bot_schedule.interval_str, bot_schedule.running_type)

        if not has_old_intervals:
            BotScheduleHelper.utils.remove_job(cron, old_comment)

        if has_changed or not has_old_intervals:
            BotScheduleHelper.utils.save_cron(cron)
        return bot_schedule if not no_update else (cron, has_changed)

    @staticmethod
    def __create_job(cron: CronTab, interval_str: str, running_type: BotScheduleRunningType | None = None) -> bool:
        comment = None
        if running_type:
            if BotSchedule.RUNNING_TYPES_WITH_START_AT.count(running_type) > 0:
                comment = f"scheduled {interval_str}"
        if comment is None:
            comment = interval_str

        BotScheduleHelper.utils.create_job(cron, interval_str, f"/app/scripts/run_bot_cron.sh '{comment}'", comment)
        return True

    @staticmethod
    def __remove_job(cron: CronTab, status: BotScheduleStatus, interval_str: str):
        if status == BotScheduleStatus.Pending:
            interval_str = f"scheduled {interval_str}"
        BotScheduleHelper.utils.remove_job(cron, interval_str)

    @overload
    @staticmethod
    def __has_interval_schedule(interval_str: str, status: BotScheduleStatus) -> bool: ...
    @overload
    @staticmethod
    def __has_interval_schedule(
        interval_str: list[tuple[str, BotScheduleStatus]],
    ) -> list[SnowflakeID]: ...
    @staticmethod
    def __has_interval_schedule(
        interval_str: str | list[tuple[str, BotScheduleStatus]],
        status: BotScheduleStatus | None = None,
    ) -> bool | list[SnowflakeID]:
        if status is None:
            interval_str = cast(list[tuple[str, BotScheduleStatus]], interval_str)
            query = SqlBuilder.select.column(BotSchedule.column("id")).where(
                tuple_(BotSchedule.column("interval_str"), BotSchedule.column("status")).in_(interval_str)
            )
        else:
            interval_str = cast(str, interval_str)
            query = (
                SqlBuilder.select.table(BotSchedule)
                .where((BotSchedule.column("interval_str") == interval_str) & (BotSchedule.column("status") == status))
                .limit(1)
            )

        result = False
        with DbSession.use(readonly=True) as db:
            result = db.exec(query)
            if status is None:
                result = cast(list[SnowflakeID], result.all())
            else:
                result = bool(result.first())
        return result
