from json import dumps, loads
from pathlib import Path
from langboard.external_import.contract import ExternalWorkBundle
from langboard.external_import.importer import ExternalWorkImporter
from langboard_shared.core.bootstrap import BaseCommand, BaseCommandOptions
from pydantic import Field


class ImportExternalWorkCommandOptions(BaseCommandOptions):
    # Commander creates an empty Pydantic namespace before argparse populates it.
    # Keep CLI-required validation at the command boundary instead of making
    # namespace construction fail before the supplied arguments are parsed.
    project_uid: str = Field(default="", description="Target project UID")
    actor_uid: str = Field(default="", description="Administrator, owner, or full-access actor UID")
    attachments_root: str = Field(default="", description="Root directory for attachment files")
    dry_run: bool = Field(default=False, description="Validate without writing")


class ImportExternalWorkCommand(BaseCommand):
    @staticmethod
    def is_only_in_dev() -> bool:
        return False

    @property
    def option_class(self) -> type[ImportExternalWorkCommandOptions]:
        return ImportExternalWorkCommandOptions

    @property
    def command(self) -> str:
        return "import:work"

    @property
    def positional_name(self) -> str:
        return "bundle file"

    @property
    def description(self) -> str:
        return "Atomically import a provider-neutral external work bundle"

    @property
    def choices(self) -> list[str] | None:
        return None

    @property
    def store_type(self) -> type[str]:
        return str

    def execute(self, bundle_file: str, options: ImportExternalWorkCommandOptions) -> None:
        if not options.project_uid.strip():
            raise ValueError("--project-uid is required")
        if not options.actor_uid.strip():
            raise ValueError("--actor-uid is required")
        path = Path(bundle_file).resolve()
        bundle = ExternalWorkBundle.model_validate(loads(path.read_text()))
        attachments_root = Path(options.attachments_root) if options.attachments_root else None
        receipt = ExternalWorkImporter(attachments_root).import_bundle(
            bundle,
            project_uid=options.project_uid,
            actor_uid=options.actor_uid,
            dry_run=options.dry_run,
        )
        print(dumps(receipt.model_dump(), sort_keys=True, separators=(",", ":")))
