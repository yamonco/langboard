from argparse import ArgumentParser
from pathlib import Path
from docling.document_converter import DocumentConverter


def convert_document(source: Path, destination: Path) -> None:
    result = DocumentConverter().convert(source)
    destination.write_text(result.document.export_to_markdown(), encoding="utf-8")


def main() -> None:
    parser = ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("destination", type=Path)
    args = parser.parse_args()
    convert_document(args.source, args.destination)


if __name__ == "__main__":
    main()
