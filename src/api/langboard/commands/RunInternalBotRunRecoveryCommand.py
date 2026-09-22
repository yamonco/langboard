from langboard_shared.ai.BoardChatAttachment import schedule_board_chat_attachment_reconciliation
from langboard_shared.core.bootstrap import BaseCommand, BaseCommandOptions
from langboard_shared.domain.models.InternalBotRun import InternalBotRunKind
from langboard_shared.domain.services import DomainService


class RunInternalBotRunRecoveryCommandOptions(BaseCommandOptions):
    pass


class RunInternalBotRunRecoveryCommand(BaseCommand[RunInternalBotRunRecoveryCommandOptions]):
    @staticmethod
    def is_only_in_dev() -> bool:
        return False

    @property
    def option_class(self) -> type[RunInternalBotRunRecoveryCommandOptions]:
        return RunInternalBotRunRecoveryCommandOptions

    @property
    def command(self) -> str:
        return "run:internal-bot-runs:recover"

    @property
    def positional_name(self) -> str:
        return ""

    @property
    def description(self) -> str:
        return "Reconcile expired internal bot runs"

    @property
    def choices(self) -> list[str] | None:
        return None

    @property
    def store_type(self) -> type[bool] | type[str]:
        return bool

    def execute(self, _: RunInternalBotRunRecoveryCommandOptions) -> None:
        with DomainService.use() as service:
            recovered = service.internal_bot_run.recover_expired()
            for run in recovered:
                if run.kind == InternalBotRunKind.BoardChat:
                    schedule_board_chat_attachment_reconciliation(run.get_uid())
