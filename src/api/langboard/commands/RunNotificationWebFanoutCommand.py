from langboard_shared.core.bootstrap import BaseCommand, BaseCommandOptions
from langboard_shared.tasks.notifications.NotificationWebFanoutTask import (
    purge_terminal_email_deliveries,
    recover_pending_email_delivery,
    recover_pending_web_fanout,
)


class RunNotificationWebFanoutCommandOptions(BaseCommandOptions):
    pass


class RunNotificationWebFanoutCommand(BaseCommand):
    @staticmethod
    def is_only_in_dev() -> bool:
        return False

    @property
    def option_class(self) -> type[RunNotificationWebFanoutCommandOptions]:
        return RunNotificationWebFanoutCommandOptions

    @property
    def command(self) -> str:
        return "run:notification:recover"

    @property
    def positional_name(self) -> str:
        return ""

    @property
    def description(self) -> str:
        return "Recover pending web fanout and email delivery"

    @property
    def choices(self) -> list[str] | None:
        return None

    @property
    def store_type(self) -> type[bool] | type[str]:
        return bool

    def execute(self, _: RunNotificationWebFanoutCommandOptions) -> None:
        try:
            recover_pending_web_fanout()
        finally:
            try:
                recover_pending_email_delivery()
            finally:
                purge_terminal_email_deliveries()
