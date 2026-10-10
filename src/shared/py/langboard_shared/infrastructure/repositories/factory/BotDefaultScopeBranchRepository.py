from ....core.domain import BaseRepository
from ....domain.models import BotDefaultScopeBranch


class BotDefaultScopeBranchRepository(BaseRepository[BotDefaultScopeBranch]):
    @staticmethod
    def model_cls():
        return BotDefaultScopeBranch

    @staticmethod
    def name() -> str:
        return "bot_default_scope_branch"
