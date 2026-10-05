from collections.abc import Callable
from hashlib import sha256
from importlib.util import find_spec
from json import dumps, loads
from os import unlink
from pathlib import Path
from queue import Empty, Queue
from subprocess import DEVNULL, PIPE, CalledProcessError, Popen, TimeoutExpired
from sys import executable
from tempfile import NamedTemporaryFile
from threading import Thread
from time import monotonic
from ...core.broker import Broker
from ...core.routing import SocketTopic
from ...core.storage import Storage
from ...core.types import SnowflakeID
from ...domain.models import CardAttachment, CardMetadata
from ...domain.services import DomainService
from ...Env import Env
from .DocumentKeywords import keyword_languages, normalize_keywords


@Broker.wrap_async_task_decorator
async def index_card_attachment(request: str):
    service = DomainService()
    try:
        payload = loads(request)
        if not isinstance(payload, dict):
            return
        attachment_uid = payload.get("attachment_uid")
        # Compatibility with pre-snapshot queued attachment messages, without auto-authorizing them.
        if not attachment_uid and payload.get("id"):
            attachment_uid = SnowflakeID(int(payload["id"])).to_short_code()
        generation = payload.get("generation")
        attachment = service.card_attachment.get_by_id_like(attachment_uid)
        if attachment:
            _index_card_attachment(service, attachment, generation=generation)
    finally:
        service.close()


def _index_card_attachment(
    service: DomainService, attachment: CardAttachment, *, generation: str | None = None
) -> None:
    current_attachment = service.card_attachment.get_by_id_like(attachment.get_uid())
    if not current_attachment:
        return

    card = service.card.get_by_id_like(current_attachment.card_id)
    if not card or not service.project.get_by_id_like(card.project_id):
        return

    temp_path = ""
    try:
        document = service.docling_metadata.get_document_by_attachment_uid(
            CardMetadata, card, current_attachment.get_uid()
        )
        if generation is not None and (not document or document.get("generation") != generation):
            return
        generation = generation or (document.get("generation") if document else None)
        vision_config = document.get("vision_config") if document else None
        # Only an upload or explicit attachment action may authorize conversion.
        if not isinstance(vision_config, dict):
            return
        binding = service.internal_bot.get_by_id_like(vision_config.get("binding_uid"))
        if not binding:
            raise ValueError("The document vision binding is no longer available")
        binding_config = loads(binding.value)
        if str(binding_config.get("base_url", "")).rstrip("/") != str(vision_config.get("base_url", "")).rstrip("/"):
            raise ValueError("The document provider changed; request processing again from the attachment")
        private_config = {**vision_config, "api_key": binding_config.get("api_key", "")}
        private_config.pop("binding_uid", None)
        if find_spec("docling") is None:
            raise RuntimeError(
                "Document processing unavailable: install the document-processing extra in the broker worker."
            )
        if not service.docling_metadata.claim_document(
            CardMetadata, card, current_attachment.get_uid(), current_attachment.filename, generation=generation
        ):
            return
        claimed = service.docling_metadata.get_document_by_attachment_uid(
            CardMetadata, card, current_attachment.get_uid()
        )
        generation = claimed.get("generation") if isinstance(claimed, dict) else generation
        service.docling_metadata.publish_update(CardMetadata, card, SocketTopic.BoardCard)
        with NamedTemporaryFile(delete=False, suffix=Path(current_attachment.filename).suffix) as temp_file:
            temp_path = temp_file.name
            downloaded = Storage.download_file(current_attachment.file, temp_file.file)
            file_size = temp_file.tell()

        if not downloaded or file_size == 0:
            raise ValueError("Attachment file could not be read.")
        if file_size > Env.MAX_FILE_SIZE_MB * 1024 * 1024:
            raise ValueError(f"Attachment exceeds the {Env.MAX_FILE_SIZE_MB} MB indexing limit.")

        def progress(completed: int, total: int | None) -> None:
            changed = service.docling_metadata.mark_document_processing(
                CardMetadata,
                card,
                current_attachment.get_uid(),
                current_attachment.filename,
                completed,
                total,
                generation=generation,
            )
            if not changed:
                raise InterruptedError("Document processing request superseded or deleted")
            service.docling_metadata.publish_update(CardMetadata, card, SocketTopic.BoardCard)

        keywords: dict[str, list[str]] = {}
        languages = keyword_languages(private_config)

        def collect_keywords(value: dict) -> None:
            normalized = normalize_keywords(value, languages)
            for language, words in normalized.items():
                keywords[language] = normalize_keywords(
                    {language: keywords.get(language, []) + words}, [language], limit=32
                ).get(language, [])

        progress(0, None)
        markdown = _convert_to_markdown(
            temp_path, on_progress=progress, vision_value=dumps(private_config), on_keywords=collect_keywords
        )
        service.docling_metadata.mark_document_indexed(
            CardMetadata,
            card,
            current_attachment.get_uid(),
            document_type=service.docling_metadata.detect_document_type(current_attachment.filename) or "unknown",
            content_hash=_get_content_hash(temp_path),
            content={
                "filename": current_attachment.filename,
                "markdown": markdown,
                "search_keywords": keywords,
            },
            generation=generation,
        )
        service.docling_metadata.publish_update(CardMetadata, card, SocketTopic.BoardCard)
    except Exception as error:
        service.docling_metadata.mark_document_failed(
            CardMetadata,
            card,
            current_attachment.get_uid(),
            current_attachment.filename,
            f"{type(error).__name__}: {error}",
            generation=generation,
        )
        service.docling_metadata.publish_update(CardMetadata, card, SocketTopic.BoardCard)
    finally:
        if temp_path:
            try:
                unlink(temp_path)
            except OSError:
                pass


def _convert_to_markdown(
    source: str,
    on_progress: Callable[[int, int], None] | None = None,
    *,
    vision_value: str | None = None,
    on_keywords: Callable[[dict], None] | None = None,
) -> str:
    output_path = ""
    try:
        with NamedTemporaryFile(delete=False, suffix=".md") as output_file:
            output_path = output_file.name

        command = [executable, "-m", "langboard_shared.tasks.docling.DoclingConverter", source, output_path]
        if vision_value is not None:
            command.append("--vision-config-stdin")
        with Popen(command, stdin=PIPE, stdout=PIPE, stderr=DEVNULL, text=True) as process:
            if process.stdin is not None:
                if vision_value is not None:
                    process.stdin.write(vision_value)
                process.stdin.close()
            events: Queue[dict | None] = Queue()

            def read_progress() -> None:
                try:
                    assert process.stdout is not None
                    for line in process.stdout:
                        if line.startswith(("LANGBOARD_DOCLING_PROGRESS:", "LANGBOARD_DOCLING_KEYWORDS:")):
                            try:
                                events.put(loads(line.split(":", 1)[1]))
                            except ValueError:
                                pass
                finally:
                    events.put(None)

            reader = Thread(target=read_progress, daemon=True)
            reader.start()
            deadline = monotonic() + Env.DOCLING_CONVERSION_TIMEOUT_SECONDS
            try:
                while True:
                    remaining = deadline - monotonic()
                    if remaining <= 0:
                        raise TimeoutExpired(command, Env.DOCLING_CONVERSION_TIMEOUT_SECONDS)
                    try:
                        event = events.get(timeout=min(remaining, 1))
                    except Empty:
                        continue
                    if event is None:
                        break
                    if not isinstance(event, dict):
                        continue
                    if on_keywords and "keywords" in event:
                        on_keywords(event["keywords"])
                    completed, total = event.get("completed_pages"), event.get("total_pages")
                    if (
                        on_progress
                        and type(completed) is int
                        and type(total) is int
                        and 0 <= completed <= total
                        and total > 0
                    ):
                        on_progress(completed, total)
                process.wait(timeout=max(0.01, deadline - monotonic()))
                if process.returncode:
                    raise CalledProcessError(process.returncode, command)
            finally:
                if process.poll() is None:
                    process.kill()
                reader.join(timeout=1)
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
