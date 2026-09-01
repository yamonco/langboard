from typing import Literal, TypeVar, cast, overload
from ....core.db import BaseDbModel, DbSession, SqlBuilder
from ....core.domain import BaseRepository
from ....core.types.ParamTypes import TBaseParam, TUserOrBot
from ....domain.models import Bot, User
from ....domain.models.bases import BaseReactionModel
from ....helpers import InfraHelper


_TReactionModel = TypeVar("_TReactionModel", bound=BaseReactionModel)


class ReactionRepository(BaseRepository):
    @staticmethod
    def name() -> str:
        return "reaction"

    def get_all(
        self, model_cls: type[_TReactionModel], targets: BaseDbModel | TBaseParam | list[BaseDbModel | TBaseParam]
    ):
        if not isinstance(targets, list):
            targets = [targets]

        target_ids = [InfraHelper.convert_id(target) for target in targets]

        records = []
        with DbSession.use(readonly=True) as db:
            result = db.exec(
                SqlBuilder.select.tables(model_cls, User, Bot)
                .outerjoin(User, model_cls.column("user_id") == User.column("id"))
                .outerjoin(Bot, model_cls.column("bot_id") == Bot.column("id"))
                .where(model_cls.column(model_cls.get_target_column_name()).in_(target_ids))
            )
            records = result.all()
        return records

    def get_one(
        self,
        user_or_bot: TUserOrBot,
        model_cls: type[_TReactionModel],
        target: BaseDbModel | TBaseParam,
        reaction_type: str,
    ) -> _TReactionModel | None:
        target_id = InfraHelper.convert_id(target)

        user_or_bot_column = (
            model_cls.column("user_id") if isinstance(user_or_bot, User) else model_cls.column("bot_id")
        )
        reaction = None
        with DbSession.use(readonly=True) as db:
            result = db.exec(
                SqlBuilder.select.table(model_cls)
                .where(
                    (user_or_bot_column == user_or_bot.id)
                    & (model_cls.column(model_cls.get_target_column_name()) == target_id)
                    & (model_cls.column("reaction_type") == reaction_type)
                )
                .limit(1)
            )
            reaction = result.first()
        return reaction

    @overload
    def toggle(
        self,
        user_or_bot: TUserOrBot,
        model_cls: type[_TReactionModel],
        target: BaseDbModel | TBaseParam,
        should_react: Literal[True],
        reaction_type: str,
        reaction: None = None,
    ): ...
    @overload
    def toggle(
        self,
        user_or_bot: TUserOrBot,
        model_cls: type[_TReactionModel],
        target: BaseDbModel | TBaseParam,
        should_react: Literal[False],
        reaction_type: str,
        reaction: _TReactionModel,
    ): ...
    def toggle(
        self,
        user_or_bot: TUserOrBot,
        model_cls: type[_TReactionModel],
        target: BaseDbModel | TBaseParam,
        should_react: bool,
        reaction_type: str,
        reaction: _TReactionModel | None = None,
    ):
        target_id = InfraHelper.convert_id(target)

        with DbSession.use(readonly=False) as db:
            if should_react:
                reaction_params = {
                    "reaction_type": reaction_type,
                    model_cls.get_target_column_name(): target_id,
                }

                if isinstance(user_or_bot, User):
                    reaction_params["user_id"] = user_or_bot.id
                else:
                    reaction_params["bot_id"] = user_or_bot.id

                reaction = model_cls(**reaction_params)
                db.insert(reaction)
            else:
                db.delete(cast(BaseReactionModel, reaction))
