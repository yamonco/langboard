from langboard_shared.core.bootstrap import BaseCommand, BaseCommandOptions
from langboard_shared.domain.services import DomainService


class RunOllamaModelPullRecoveryCommandOptions(BaseCommandOptions):
    pass


class RunOllamaModelPullRecoveryCommand(BaseCommand):
    @staticmethod
    def is_only_in_dev() -> bool:
        return False

    @property
    def option_class(self) -> type[RunOllamaModelPullRecoveryCommandOptions]:
        return RunOllamaModelPullRecoveryCommandOptions

    @property
    def command(self) -> str:
        return "run:ollama-pulls:recover"

    @property
    def positional_name(self) -> str:
        return ""

    @property
    def description(self) -> str:
        return "Recover accepted Ollama model pulls"

    @property
    def choices(self) -> list[str] | None:
        return None

    @property
    def store_type(self) -> type[bool] | type[str]:
        return bool

    def execute(self, _: RunOllamaModelPullRecoveryCommandOptions) -> None:
        with DomainService.use() as service:
            service.ollama_model_pull.recover()
