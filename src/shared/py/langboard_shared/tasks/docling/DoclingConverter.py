from argparse import ArgumentParser
from json import dumps, loads
from pathlib import Path
from sys import stdin
from docling.datamodel.base_models import ConversionStatus
from docling.document_converter import DocumentConverter
from .DocumentVision import ALIAS, create_vision_converter


PROGRESS_PREFIX = "LANGBOARD_DOCLING_PROGRESS:"


def _report_progress(completed: int, total: int) -> None:
    print(PROGRESS_PREFIX + dumps({"completed_pages": completed, "total_pages": total}), flush=True)


def _report_keywords(page: int, keywords: dict[str, list[str]]) -> None:
    print("LANGBOARD_DOCLING_KEYWORDS:" + dumps({"page": page, "keywords": keywords}, ensure_ascii=False), flush=True)


def convert_document(
    source: Path, destination: Path, vision_value: str | None = None, document_output: Path | None = None
) -> None:
    converter = DocumentConverter()
    if source.suffix.lower() in {".pdf", ".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".webp"}:
        from ...domain.services import DomainService
        from ...Env import Env

        service = DomainService()
        try:
            binding = service.internal_bot.get_document_vision_binding() if vision_value is None else None
            if vision_value is None and (not binding or not service.internal_bot.is_document_processing_enabled()):
                raise ValueError(f"Configure a default internal AI {ALIAS} provider before indexing PDF/images")
            allowed = {
                url.strip().rstrip("/")
                for url in Env.get_from_env("MODEL_PROVIDER_ALLOWED_BASE_URLS", "").split(",")
                if url.strip()
            }
            converter = create_vision_converter(
                vision_value or binding.value, allowed, on_progress=_report_progress, on_keywords=_report_keywords
            )
        finally:
            service.close()
    result = converter.convert(source)
    if result.status != ConversionStatus.SUCCESS:
        raise ValueError("Document conversion did not complete; attachment remains available")
    destination.write_text(result.document.export_to_markdown(), encoding="utf-8")
    if document_output is not None:
        structural = result.document.model_copy(update={
            "pages": {key: page.model_copy(update={"image": None}) for key, page in result.document.pages.items()},
            "pictures": [picture.model_copy(update={"image": None}) for picture in result.document.pictures],
        })
        document_output.write_text(dumps(structural.export_to_dict(), ensure_ascii=False), encoding="utf-8")


def main() -> None:
    parser = ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("destination", type=Path)
    parser.add_argument("--vision-config-stdin", action="store_true")
    parser.add_argument("--document-output", type=Path)
    args = parser.parse_args()
    value = stdin.read() if args.vision_config_stdin else None
    if value is not None:
        loads(value)  # Validate the private worker payload before conversion.
    convert_document(args.source, args.destination, value, args.document_output)


if __name__ == "__main__":
    main()
