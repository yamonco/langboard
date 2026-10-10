from langboard_shared.core.bootstrap import BaseCommand, BaseCommandOptions
from langboard_shared.core.broker import Broker


class RunBrokerCommandOptions(BaseCommandOptions):
    pass


class RunBrokerCommand(BaseCommand):
    @staticmethod
    def is_only_in_dev() -> bool:
        return False

    @property
    def option_class(self) -> type[RunBrokerCommandOptions]:
        return RunBrokerCommandOptions

    @property
    def command(self) -> str:
        return "run:broker"

    @property
    def positional_name(self) -> str:
        return ""

    @property
    def description(self) -> str:
        return "Run the broker service"

    @property
    def choices(self) -> list[str] | None:
        return None

    @property
    def store_type(self) -> type[bool] | type[str]:
        return bool

    def execute(self, _: RunBrokerCommandOptions) -> None:
        from ..apps import GitHubHealthTask  # noqa: F401

        Broker.start(argv=["worker", "--loglevel=info", "--concurrency=1", "--pool=solo"])
