from argparse import ArgumentParser
from pathlib import Path
from docling.datamodel.base_models import ConversionStatus
from docling.document_converter import DocumentConverter
from .DocumentVision import ALIAS, create_vision_converter


def convert_document(source: Path, destination: Path) -> None:
    converter = DocumentConverter()
    if source.suffix.lower() in {".pdf", ".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".webp"}:
        from ...domain.services import DomainService
        from ...Env import Env

        service = DomainService()
        try:
            binding = service.internal_bot.get_document_vision_binding()
            if not binding:
                raise ValueError(f"Configure a default internal AI {ALIAS} provider before indexing PDF/images")
            allowed = {
                url.strip().rstrip("/")
                for url in Env.get_from_env("MODEL_PROVIDER_ALLOWED_BASE_URLS", "").split(",")
                if url.strip()
            }
            converter = create_vision_converter(binding.value, allowed)
        finally:
            service.close()
    result = converter.convert(source)
    if result.status != ConversionStatus.SUCCESS:
        raise ValueError("Document conversion did not complete; attachment remains available")
    destination.write_text(result.document.export_to_markdown(), encoding="utf-8")


def main() -> None:
    parser = ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("destination", type=Path)
    args = parser.parse_args()
    convert_document(args.source, args.destination)


if __name__ == "__main__":
    main()
