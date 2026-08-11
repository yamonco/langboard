from typing import Any, overload
from ....ai import BotDefaultTrigger
from ....core.db import BaseDbModel, DbSession, SqlBuilder
from ....core.logger import Logger
from ....core.types.BotRelatedTypes import AVAILABLE_BOT_TARGET_TABLES
from ....core.utils.decorators import staticclass
from ....domain.models import Bot, Project
from ....domain.models.bases import BotTriggerCondition
from ....helpers import BotHelper
from ....helpers import BotHelper as BotHelperClass
from ...webhooks import WebhookTask
from ...webhooks.utils import WebhookModel
from .requests.Utils import create_request


logger = Logger.use("bot-task")


@staticclass
class BotTaskHelper:
    @staticmethod
    def get_scoped_bots(
        condition: BotTriggerCondition, *, with_deleted_target: bool = False, **where_clauses: Any
    ) -> list[tuple[Bot, BaseDbModel]]:
        model_classes = BotHelper.get_scope_model_classes_by_condition(condition)
        records: list[tuple[Bot, BaseDbModel]] = []
        with DbSession.use(readonly=True) as db:
            for model_class in model_classes:
                column_name = model_class.get_scope_column_name()
                if column_name not in where_clauses or not where_clauses[column_name]:
                    continue

                target_table = BotHelper.get_target_table_by_bot_model("scope", model_class)
                if not target_table:
                    continue

                target_table_class = AVAILABLE_BOT_TARGET_TABLES[target_table]

                default_scope_model_cls = BotHelperClass.get_default_scope_model_class(column_name)
                if not default_scope_model_cls:
                    continue

                custom_query = (
                    SqlBuilder.select.tables(Bot, model_class, target_table_class, with_deleted=with_deleted_target)
                    .join(model_class, model_class.column("bot_id") == Bot.column("id"))
                    .join(
                        target_table_class,
                        target_table_class.column("id") == model_class.column(column_name),
                    )
                    .where(
                        (Bot.column("deleted_at").is_(None))
                        & (model_class.column("default_scope_branch_id").is_(None))
                        & (model_class.column("conditions").contains([condition.value]))
                        & (model_class.column("is_frozen") == False)  # noqa: E712
                        & (model_class.column(column_name) == where_clauses[column_name])
                    )
                )

                for clause_name in where_clauses:
                    if target_table_class.model_fields.get(clause_name):
                        custom_query = custom_query.where(
                            target_table_class.column(clause_name) == where_clauses[clause_name]
                        )

                default_query = (
                    SqlBuilder.select.tables(
                        Bot,
                        model_class,
                        default_scope_model_cls,
                        target_table_class,
                        with_deleted=with_deleted_target,
                    )
                    .join(model_class, model_class.column("bot_id") == Bot.column("id"))
                    .join(
                        default_scope_model_cls,
                        default_scope_model_cls.column("bot_default_scope_branch_id")
                        == model_class.column("default_scope_branch_id"),
                    )
                    .join(
                        target_table_class,
                        target_table_class.column("id") == model_class.column(column_name),
                    )
                    .where(
                        (Bot.column("deleted_at").is_(None))
                        & (model_class.column("default_scope_branch_id").is_not(None))
                        & (default_scope_model_cls.column("conditions").contains([condition.value]))
                        & (model_class.column("is_frozen") == False)  # noqa: E712
                        & (model_class.column(column_name) == where_clauses[column_name])
                    )
                )

                for clause_name in where_clauses:
                    if target_table_class.model_fields.get(clause_name):
                        default_query = default_query.where(
                            target_table_class.column(clause_name) == where_clauses[clause_name]
                        )

                custom_result = db.exec(custom_query)
                records.extend([(bot, scope_model) for bot, _, scope_model in custom_result.all()])

                default_result = db.exec(default_query)
                records.extend([(bot, scope_model) for bot, _, _, scope_model in default_result.all()])

        return records

    @overload
    @staticmethod
    async def run(
        bots: Bot | list[Bot],
        event: BotTriggerCondition | BotDefaultTrigger,
        data: dict[str, Any],
        project: Project | None = None,
        scope_model: BaseDbModel | None = None,
        *,
        emit_webhook: bool = True,
    ): ...
    @overload
    @staticmethod
    async def run(
        bots: list[tuple[Bot, BaseDbModel]],
        event: BotTriggerCondition | BotDefaultTrigger,
        data: dict[str, Any],
        project: Project | None = None,
        *,
        emit_webhook: bool = True,
    ): ...
    @staticmethod
    async def run(
        bots: Bot | list[Bot] | list[tuple[Bot, BaseDbModel]],
        event: BotTriggerCondition | BotDefaultTrigger,
        data: dict[str, Any],
        project: Project | None = None,
        scope_model: BaseDbModel | None = None,
        *,
        emit_webhook: bool = True,
    ):
        if not isinstance(bots, list):
            bots = [bots]

        if emit_webhook:
            WebhookTask.webhook_task(WebhookModel(event=event.value, data=data))

        for bot in bots:
            if isinstance(bot, tuple):
                bot, scope_model = bot
            request = create_request(bot, event.value, data, project, scope_model)
            if not request:
                continue
            await request.execute()
