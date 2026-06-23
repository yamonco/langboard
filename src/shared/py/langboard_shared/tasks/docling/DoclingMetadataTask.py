from os import unlink
from pathlib import Path
from tempfile import NamedTemporaryFile
from docling.document_converter import DocumentConverter
from ...core.broker import Broker
from ...core.routing import SocketTopic
from ...core.storage import Storage
from ...domain.models import CardAttachment, CardMetadata
from ...domain.services import DomainService


@Broker.wrap_async_task_decorator
async def index_card_attachment(attachment: CardAttachment):
    service = DomainService()
    current_attachment = service.card_attachment.get_by_id_like(attachment.get_uid())
    if not current_attachment:
        return

    card = service.card.get_by_id_like(current_attachment.card_id)
    if not card:
        return

    project = service.project.get_by_id_like(card.project_id)
    if not project:
        return

    file_bytes = Storage.get_file(current_attachment.file)
    if not file_bytes:
        service.docling_metadata.mark_document_failed(
            CardMetadata,
            card,
            current_attachment.get_uid(),
            current_attachment.filename,
            "Attachment file could not be read.",
        )
        service.docling_metadata.publish_update(CardMetadata, card, SocketTopic.BoardCard)
        return

    temp_path = ""
    try:
        with NamedTemporaryFile(delete=False, suffix=Path(current_attachment.filename).suffix) as temp_file:
            temp_file.write(file_bytes)
            temp_path = temp_file.name

        markdown = _convert_to_markdown(temp_path)
        service.docling_metadata.mark_document_indexed(
            CardMetadata,
            card,
            current_attachment.get_uid(),
            document_type=service.docling_metadata.detect_document_type(current_attachment.filename) or "unknown",
            content_hash=service.docling_metadata.get_content_hash(file_bytes),
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
    result = DocumentConverter().convert(source)
    return result.document.export_to_markdown()
