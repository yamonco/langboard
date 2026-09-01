from ....core.db import DbSession, SqlBuilder
from ....core.domain import BaseRepository
from ....core.types.ParamTypes import TInternalBotParam
from ....domain.models import InternalBot
from ....domain.models.InternalBot import InternalBotType
from ....helpers import InfraHelper


class InternalBotRepository(BaseRepository[InternalBot]):
    @staticmethod
    def model_cls():
        return InternalBot

    @staticmethod
    def name() -> str:
        return "internal_bot"

    def get_default_list(self) -> list[InternalBot]:
        internal_bots = []
        with DbSession.use(readonly=True) as db:
            result = db.exec(
                SqlBuilder.select.table(InternalBot).where(InternalBot.is_default == True)  # noqa: E712
            )
            internal_bots = result.all()
        return internal_bots

    def get_default_by_type(self, bot_type: InternalBotType) -> InternalBot | None:
        internal_bot = None
        with DbSession.use(readonly=True) as db:
            result = db.exec(
                SqlBuilder.select.table(InternalBot)
                .where(
                    (InternalBot.column("bot_type") == bot_type) & (InternalBot.is_default == True)  # noqa: E712
                )
                .limit(1)
            )
            internal_bot = result.first()
        return internal_bot

    def replace_default(self, internal_bot: TInternalBotParam, bot_type: InternalBotType) -> None:
        internal_bot_id = InfraHelper.convert_id(internal_bot)
        with DbSession.use(readonly=False) as db:
            db.exec(
                SqlBuilder.update.table(InternalBot)
                .values({InternalBot.column("is_default"): False})
                .where(
                    (InternalBot.column("bot_type") == bot_type) & (InternalBot.is_default == True)  # noqa: E712
                )
            )

            db.exec(
                SqlBuilder.update.table(InternalBot)
                .values({InternalBot.column("is_default"): True})
                .where(InternalBot.column("id") == internal_bot_id)
            )
