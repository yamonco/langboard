from typing import Any, Callable, TypeVar
from ..core.db import BaseDbModel, DbSession, SqlBuilder
from ..core.db.queries.Select import SelectOfScalar
from ..core.types.ParamTypes import TBaseParam, TBotParam
from ..core.utils.decorators import staticclass
from ..domain.models import Bot, BotDefaultScopeBranch
from ..domain.models.bases import BaseBotScopeModel, BotTriggerCondition
from ..helpers import BotHelper, InfraHelper


_TBotScopeModel = TypeVar("_TBotScopeModel", bound=BaseBotScopeModel)


@staticclass
class BotScopeHelper:
    @staticmethod
    def get_by_id_like(
        model_cls: type[_TBotScopeModel], model: _TBotScopeModel | TBaseParam | None
    ) -> _TBotScopeModel | None:
        record = InfraHelper.get_by_id_like(model_cls, model)
        return record

    @staticmethod
    def get_list(
        model_cls: type[_TBotScopeModel],
        set_query: Callable[[SelectOfScalar[_TBotScopeModel]], SelectOfScalar[_TBotScopeModel]] | None = None,
        limit: int | None = None,
        **where_clauses: Any,
    ) -> list[_TBotScopeModel]:
        """Return bot scopes, optionally enforcing a database row limit."""

        query = SqlBuilder.select.table(model_cls)

        if set_query:
            query = set_query(query)

        if where_clauses:
            query = InfraHelper.where_recursive(query, model_cls, **where_clauses)
        if limit is not None:
            query = query.limit(limit)

        records = []
        with DbSession.use(readonly=True) as db:
            result = db.exec(query)
            records = result.all()

        return records

    @staticmethod
    def create(
        model_cls: type[_TBotScopeModel],
        bot: TBotParam | None,
        scope: BaseDbModel,
        conditions: list[BotTriggerCondition],
        **kwargs: Any,
    ) -> _TBotScopeModel | None:
        bot = InfraHelper.get_by_id_like(Bot, bot)
        if not bot:
            return None

        model_params = {
            "bot_id": bot.id,
            "conditions": conditions,
            **kwargs,
        }

        model_params[model_cls.get_scope_column_name()] = scope.id

        model = model_cls(**model_params)

        with DbSession.use(readonly=False) as db:
            db.insert(model)

        return model

    @staticmethod
    def upsert_conditions(
        model_cls: type[_TBotScopeModel],
        bot: TBotParam | None,
        scope: BaseDbModel,
        conditions: list[BotTriggerCondition],
        **kwargs: Any,
    ) -> tuple[_TBotScopeModel, bool] | None:
        bot = InfraHelper.get_by_id_like(Bot, bot)
        if not bot:
            return None

        scope_column_name = model_cls.get_scope_column_name()
        records = BotScopeHelper.get_list(model_cls, None, bot_id=bot.id, **{scope_column_name: scope.id})

        if records:
            model = records[0]
            if model.conditions != conditions or model.default_scope_branch_id is not None:
                model.conditions = conditions
                model.default_scope_branch_id = None
                with DbSession.use(readonly=False) as db:
                    db.update(model)
            return model, False

        model = BotScopeHelper.create(model_cls, bot, scope, conditions, **kwargs)
        if not model:
            return None

        return model, True

    @staticmethod
    def toggle_trigger_condition(
        model_cls: type[_TBotScopeModel], model: _TBotScopeModel | TBaseParam | None, condition: BotTriggerCondition
    ):
        model = InfraHelper.get_by_id_like(model_cls, model)
        if not model:
            return False

        if condition not in model_cls.get_available_conditions():
            return True

        if model.default_scope_branch_id:
            scope_column_name = model_cls.get_scope_column_name()
            default_scope_model_cls = BotHelper.get_default_scope_model_class(scope_column_name)

            if default_scope_model_cls:
                default_scopes = InfraHelper.get_all_by(
                    default_scope_model_cls, "bot_default_scope_branch_id", model.default_scope_branch_id
                )

                if default_scopes:
                    conditions = [*default_scopes[0].conditions]
                else:
                    conditions = []

                model.default_scope_branch_id = None
            else:
                conditions = []
        else:
            conditions = [*model.conditions]

        should_enable = condition not in conditions
        if should_enable:
            conditions.append(condition)
        else:
            conditions.remove(condition)

        model.conditions = conditions

        with DbSession.use(readonly=False) as db:
            db.update(model)

        return True

    @staticmethod
    def set_freeze(
        model_cls: type[_TBotScopeModel], model: _TBotScopeModel | TBaseParam | None, is_frozen: bool
    ) -> _TBotScopeModel | None:
        model = InfraHelper.get_by_id_like(model_cls, model)
        if not model:
            return None

        model.is_frozen = is_frozen
        with DbSession.use(readonly=False) as db:
            db.update(model)

        return model

    @staticmethod
    def delete(model_cls: type[_TBotScopeModel], model: _TBotScopeModel | TBaseParam | None) -> _TBotScopeModel | None:
        model = InfraHelper.get_by_id_like(model_cls, model)
        if not model:
            return None

        with DbSession.use(readonly=False) as db:
            db.delete(model)

        return model

    @staticmethod
    def delete_by_scope(model_cls: type[_TBotScopeModel], scope: BaseDbModel) -> list[_TBotScopeModel]:
        query = SqlBuilder.select.table(model_cls).where(
            model_cls.column(model_cls.get_scope_column_name()) == scope.id
        )

        records = []
        with DbSession.use(readonly=True) as db:
            result = db.exec(query)
            records = result.all()

        if not records:
            return []

        with DbSession.use(readonly=False) as db:
            for record in records:
                db.delete(record)

        return records

    @staticmethod
    def apply_default_scope(
        model_cls: type[_TBotScopeModel],
        bot: TBotParam | None,
        scope: BaseDbModel,
        default_scope_branch_uid: str | None,
    ) -> tuple[_TBotScopeModel, bool] | None:
        bot = InfraHelper.get_by_id_like(Bot, bot)
        if not bot:
            return None

        if default_scope_branch_uid:
            default_scope_branch = InfraHelper.get_by_id_like(BotDefaultScopeBranch, default_scope_branch_uid)
            if not default_scope_branch:
                return None

            upserted = BotScopeHelper.upsert_conditions(model_cls, bot, scope, [])
            if not upserted:
                return None

            bot_scope, is_created = upserted

            bot_scope.default_scope_branch_id = default_scope_branch.id
            with DbSession.use(readonly=False) as db:
                db.update(bot_scope)

            return bot_scope, is_created
        else:
            scope_column_name = model_cls.get_scope_column_name()
            existing_scopes = BotScopeHelper.get_list(model_cls, None, bot_id=bot.id, **{scope_column_name: scope.id})
            if not existing_scopes:
                return None

            bot_scope = existing_scopes[0]
            if bot_scope.default_scope_branch_id is not None:
                bot_scope.default_scope_branch_id = None
                with DbSession.use(readonly=False) as db:
                    db.update(bot_scope)

            return bot_scope, False
