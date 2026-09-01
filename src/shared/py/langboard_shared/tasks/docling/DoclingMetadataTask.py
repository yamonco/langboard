from hashlib import sha256
from os import unlink
from pathlib import Path
from subprocess import run
from sys import executable
from tempfile import NamedTemporaryFile
from ...core.broker import Broker
from ...core.routing import SocketTopic
from ...core.storage import Storage
from ...domain.models import CardAttachment, CardMetadata
from ...domain.services import DomainService
from ...Env import Env


@Broker.wrap_async_task_decorator
async def index_card_attachment(attachment: CardAttachment):
    service = DomainService()
    try:
        _index_card_attachment(service, attachment)
    finally:
        service.close()


def _index_card_attachment(service: DomainService, attachment: CardAttachment) -> None:
    current_attachment = service.card_attachment.get_by_id_like(attachment.get_uid())
    if not current_attachment:
        return

    card = service.card.get_by_id_like(current_attachment.card_id)
    if not card or not service.project.get_by_id_like(card.project_id):
        return

    temp_path = ""
    try:
        with NamedTemporaryFile(delete=False, suffix=Path(current_attachment.filename).suffix) as temp_file:
            temp_path = temp_file.name
            downloaded = Storage.download_file(current_attachment.file, temp_file.file)
            file_size = temp_file.tell()

        if not downloaded or file_size == 0:
            raise ValueError("Attachment file could not be read.")
        if file_size > Env.MAX_FILE_SIZE_MB * 1024 * 1024:
            raise ValueError(f"Attachment exceeds the {Env.MAX_FILE_SIZE_MB} MB indexing limit.")

        markdown = _convert_to_markdown(temp_path)
        service.docling_metadata.mark_document_indexed(
            CardMetadata,
            card,
            current_attachment.get_uid(),
            document_type=service.docling_metadata.detect_document_type(current_attachment.filename) or "unknown",
            content_hash=_get_content_hash(temp_path),
            content={
                "filename": current_attachment.filename,
                "markdown": markdown,
            },
        )
        service.docling_metadata.publish_update(CardMetadata, card, SocketTopic.BoardCard)
    except Exception as error:
        service.docling_metadata.mark_document_failed(
            CardMetadata,
            card,
            current_attachment.get_uid(),
            current_attachment.filename,
            f"{type(error).__name__}: {error}",
        )
        service.docling_metadata.publish_update(CardMetadata, card, SocketTopic.BoardCard)
    finally:
        if temp_path:
            try:
                unlink(temp_path)
            except OSError:
                pass


def _convert_to_markdown(source: str) -> str:
    output_path = ""
    try:
        with NamedTemporaryFile(delete=False, suffix=".md") as output_file:
            output_path = output_file.name

        run(
            [
                executable,
                "-m",
                "langboard_shared.tasks.docling.DoclingConverter",
                source,
                output_path,
            ],
            check=True,
            timeout=Env.DOCLING_CONVERSION_TIMEOUT_SECONDS,
        )
        return Path(output_path).read_text(encoding="utf-8")
    finally:
        if output_path:
            try:
                unlink(output_path)
            except OSError:
                pass


def _get_content_hash(source: str) -> str:
    content_hash = sha256()
    with open(source, "rb") as source_file:
        while chunk := source_file.read(1024 * 1024):
            content_hash.update(chunk)
    return content_hash.hexdigest()
