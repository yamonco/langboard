from ....core.db import DbSession, SqlBuilder
from ....core.domain import BaseRepository
from ....core.types.ParamTypes import TBotParam
from ....domain.models import BotDefaultScopeBranch
from ....helpers import InfraHelper


class BotDefaultScopeBranchRepository(BaseRepository[BotDefaultScopeBranch]):
    @staticmethod
    def model_cls() -> type[BotDefaultScopeBranch]:
        return BotDefaultScopeBranch

    @staticmethod
    def name() -> str:
        return "bot_default_scope_branch"

    def get_by_bot_and_name(self, bot: TBotParam, name: str) -> BotDefaultScopeBranch | None:
        bot_id = InfraHelper.convert_id(bot)
        with DbSession.use(readonly=True) as db:
            return db.exec(
                SqlBuilder.select.table(BotDefaultScopeBranch)
                .where(
                    (BotDefaultScopeBranch.column("bot_id") == bot_id) & (BotDefaultScopeBranch.column("name") == name)
                )
                .limit(1)
            ).first()
