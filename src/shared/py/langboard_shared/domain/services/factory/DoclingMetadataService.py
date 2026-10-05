import json
from enum import Enum
from hashlib import sha256
from pathlib import Path
from typing import Any
from uuid import uuid4
from sqlalchemy import update
from ....core.db import BaseDbModel, DbSession, SqlBuilder
from ....core.domain import BaseDomainService
from ....core.routing import SocketTopic
from ....core.types import SafeDateTime
from ....domain.models import CardAttachment, CardMetadata
from ....domain.models.bases import BaseMetadataModel
from ....Env import Env
from ....helpers import InfraHelper
from ....publishers import MetadataPublisher
from ....tasks.docling.DocumentKeywords import KEYWORD_LANGUAGES, normalize_keywords


DOCLING_DOCUMENTS_METADATA_KEY = "__system.docling_documents"

SUPPORTED_DOCLING_DOCUMENT_TYPES = {
    ".pdf": "pdf",
    ".docx": "docx",
    ".pptx": "pptx",
    ".xlsx": "xlsx",
    ".html": "html",
    ".htm": "html",
    ".md": "markdown",
    ".markdown": "markdown",
    ".csv": "csv",
    **{suffix: "image" for suffix in (".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".webp")},
}


class DoclingIndexStatus(str, Enum):
    Pending = "pending"
    Processing = "processing"
    Disabled = "disabled"
    Indexed = "indexed"
    Failed = "failed"


class DoclingMetadataService(BaseDomainService):
    @staticmethod
    def name() -> str:
        return "docling_metadata"

    def get_metadata_map(
        self, model_cls: type[BaseMetadataModel], foreign_key: str, foreign_ids: list[int]
    ) -> dict[int, dict[str, str]]:
        metadata_records = self.repo.metadata.get_by_foreign_ids_and_key(
            model_cls, foreign_key, foreign_ids, DOCLING_DOCUMENTS_METADATA_KEY
        )
        return {getattr(metadata, foreign_key): {metadata.key: metadata.value} for metadata in metadata_records}

    def detect_document_type(self, filename: str) -> str | None:
        return SUPPORTED_DOCLING_DOCUMENT_TYPES.get(Path(filename).suffix.lower())

    def get_content_hash(self, content: bytes) -> str:
        return sha256(content).hexdigest()

    def queue_document(
        self,
        model_cls: type[BaseMetadataModel],
        foreign_model: BaseDbModel,
        attachment_uid: str,
        filename: str,
        *,
        vision_config: dict[str, Any] | None = None,
        force: bool = False,
    ) -> bool:
        with DbSession.atomic() as db:
            db.exec(
                SqlBuilder.select.table(type(foreign_model))
                .where(type(foreign_model).column("id") == foreign_model.id)
                .with_for_update()
            )
            document_type = self.detect_document_type(filename)
            if not document_type:
                return False

            current = self.get_document_by_attachment_uid(model_cls, foreign_model, attachment_uid)
            if current and (
                current.get("status") in {DoclingIndexStatus.Pending.value, DoclingIndexStatus.Processing.value}
                or (not force and current.get("status") == DoclingIndexStatus.Indexed.value)
            ):
                return False
            document = {
                **(current or {}),
                "attachment_uid": attachment_uid,
                "document_type": document_type,
                "status": DoclingIndexStatus.Pending.value,
                "generation": uuid4().hex,
                "content": (current or {}).get("content", {}),
                "vision_config": vision_config,
            }
            self.upsert_document(model_cls, foreign_model, document)
            return True

    def claim_document(
        self,
        model_cls: type[BaseMetadataModel],
        foreign_model: BaseDbModel,
        attachment_uid: str,
        filename: str,
        *,
        generation: str | None = None,
    ) -> bool:
        with DbSession.atomic() as db:
            db.exec(
                SqlBuilder.select.table(type(foreign_model))
                .where(type(foreign_model).column("id") == foreign_model.id)
                .with_for_update()
            )
            current = self.get_document_by_attachment_uid(model_cls, foreign_model, attachment_uid) or {}
            if generation is not None and current.get("generation") != generation:
                return False
            if current.get("status") == DoclingIndexStatus.Indexed.value:
                return False
            if current.get("status") == DoclingIndexStatus.Processing.value:
                started = current.get("started_at")
                try:
                    from datetime import datetime

                    age = (SafeDateTime.now() - datetime.fromisoformat(started)).total_seconds()
                    if age < Env.DOCLING_CONVERSION_TIMEOUT_SECONDS + 30:
                        return False
                except (ValueError, TypeError):
                    return False
            self.upsert_document(
                model_cls,
                foreign_model,
                {
                    **current,
                    "attachment_uid": attachment_uid,
                    "started_at": SafeDateTime.now().isoformat(),
                    "generation": uuid4().hex,
                },
            )
            self.mark_document_processing(model_cls, foreign_model, attachment_uid, filename)
            return True

    def mark_document_processing(
        self,
        model_cls: type[BaseMetadataModel],
        foreign_model: BaseDbModel,
        attachment_uid: str,
        filename: str,
        completed_pages: int = 0,
        total_pages: int | None = None,
        *,
        generation: str | None = None,
    ) -> bool:
        current = self.get_document_by_attachment_uid(model_cls, foreign_model, attachment_uid) or {}
        if total_pages is not None and (total_pages < 1 or not 0 <= completed_pages <= total_pages):
            raise ValueError("Invalid document page progress")
        return self.upsert_document(
            model_cls,
            foreign_model,
            {
                **current,
                "attachment_uid": attachment_uid,
                "document_type": self.detect_document_type(filename) or "unknown",
                "status": DoclingIndexStatus.Processing.value,
                "started_at": current.get("started_at") or SafeDateTime.now().isoformat(),
                "completed_pages": completed_pages,
                "total_pages": total_pages,
                # 100% belongs to the committed indexed result, not the last inference request.
                "progress_percent": min(99, completed_pages * 100 // total_pages) if total_pages else None,
                "content": current.get("content", {}),
            },
            expected_generation=generation,
        )

    def mark_document_disabled(
        self,
        model_cls: type[BaseMetadataModel],
        foreign_model: BaseDbModel,
        attachment_uid: str,
        filename: str,
    ) -> None:
        self.upsert_document(
            model_cls,
            foreign_model,
            {
                "attachment_uid": attachment_uid,
                "document_type": self.detect_document_type(filename) or "unknown",
                "status": DoclingIndexStatus.Disabled.value,
                "content": {},
            },
        )

    def mark_document_indexed(
        self,
        model_cls: type[BaseMetadataModel],
        foreign_model: BaseDbModel,
        attachment_uid: str,
        document_type: str,
        content_hash: str | None = None,
        content: dict[str, Any] | None = None,
        *,
        generation: str | None = None,
    ) -> bool:
        current = self.get_document_by_attachment_uid(model_cls, foreign_model, attachment_uid) or {}
        document = {
            **current,
            "attachment_uid": attachment_uid,
            "document_type": document_type,
            "status": DoclingIndexStatus.Indexed.value,
            "progress_percent": 100,
            "content_hash": content_hash,
            "indexed_at": SafeDateTime.now().isoformat(),
            "content": content or {},
        }
        with DbSession.atomic() as db:
            db.exec(
                SqlBuilder.select.table(type(foreign_model))
                .where(type(foreign_model).column("id") == foreign_model.id)
                .with_for_update()
            )
            latest = self.get_document_by_attachment_uid(model_cls, foreign_model, attachment_uid)
            if generation is not None and (not latest or latest.get("generation") != generation):
                return False
            if model_cls is CardMetadata:
                attachment_id = InfraHelper.convert_id(attachment_uid)
                result = db.exec(
                    update(CardAttachment)
                    .where(CardAttachment.id == attachment_id)
                    .where(CardAttachment.card_id == foreign_model.id)
                    .where(CardAttachment.deleted_at.is_(None))
                    .values(
                        document_text="\n\n".join(
                            filter(
                                None,
                                [
                                    str((content or {}).get("markdown", "")),
                                    " ".join(
                                        word
                                        for words in normalize_keywords(
                                            (content or {}).get("search_keywords"), list(KEYWORD_LANGUAGES), limit=32
                                        ).values()
                                        for word in words
                                    ),
                                ],
                            )
                        )
                    )
                )
                if not result:
                    return False
            self.upsert_document(model_cls, foreign_model, document)
        return True

    def mark_document_failed(
        self,
        model_cls: type[BaseMetadataModel],
        foreign_model: BaseDbModel,
        attachment_uid: str,
        filename: str,
        error_message: str,
        *,
        generation: str | None = None,
    ) -> bool:
        document_type = self.detect_document_type(filename) or "unknown"
        current = self.get_document_by_attachment_uid(model_cls, foreign_model, attachment_uid)
        document = {
            **(
                current
                or {
                    "attachment_uid": attachment_uid,
                    "document_type": document_type,
                    "status": DoclingIndexStatus.Pending.value,
                    "content": {},
                }
            ),
            "document_type": document_type,
            "status": DoclingIndexStatus.Failed.value,
            "error_message": error_message,
        }
        return self.upsert_document(model_cls, foreign_model, document, expected_generation=generation)

    def load_documents(self, model_cls: type[BaseMetadataModel], foreign_model: BaseDbModel) -> list[dict[str, Any]]:
        metadata = self._load_metadata(model_cls, foreign_model)
        return self.parse_documents(metadata)

    def parse_documents(self, metadata: dict[str, str]) -> list[dict[str, Any]]:
        value = metadata.get(DOCLING_DOCUMENTS_METADATA_KEY)
        if not value:
            return []

        try:
            raw_documents = json.loads(value)
        except json.JSONDecodeError:
            return []

        if not isinstance(raw_documents, list):
            return []

        return [document for document in raw_documents if isinstance(document, dict)]

    def save_documents(
        self, model_cls: type[BaseMetadataModel], foreign_model: BaseDbModel, documents: list[dict[str, Any]]
    ) -> None:
        if documents:
            value = json.dumps(documents, ensure_ascii=False, separators=(",", ":"))
            self.repo.metadata.save(model_cls, foreign_model, DOCLING_DOCUMENTS_METADATA_KEY, value)
            return

        self.repo.metadata.delete_keys(model_cls, foreign_model, DOCLING_DOCUMENTS_METADATA_KEY)

    def get_document_by_attachment_uid(
        self, model_cls: type[BaseMetadataModel], foreign_model: BaseDbModel, attachment_uid: str
    ) -> dict[str, Any] | None:
        return next(
            (
                document
                for document in self.load_documents(model_cls, foreign_model)
                if document.get("attachment_uid") == attachment_uid
            ),
            None,
        )

    def upsert_document(
        self,
        model_cls: type[BaseMetadataModel],
        foreign_model: BaseDbModel,
        document: dict[str, Any],
        *,
        expected_generation: str | None = None,
    ) -> bool:
        attachment_uid = document["attachment_uid"]

        changed = False

        def merge(value: str | None) -> str | None:
            nonlocal changed
            documents = self.parse_documents({DOCLING_DOCUMENTS_METADATA_KEY: value or "[]"})
            current = next((entry for entry in documents if entry.get("attachment_uid") == attachment_uid), None)
            if expected_generation is not None and (not current or current.get("generation") != expected_generation):
                return None
            changed = True
            documents = [current for current in documents if current.get("attachment_uid") != attachment_uid]
            documents.append(document)
            documents.sort(key=lambda current: str(current.get("document_type") or ""))
            return json.dumps(documents, ensure_ascii=False, separators=(",", ":"))

        # Serialize the first metadata insert as well as subsequent read-modify-write updates.
        with DbSession.atomic() as db:
            db.exec(
                SqlBuilder.select.table(type(foreign_model))
                .where(type(foreign_model).column("id") == foreign_model.id)
                .with_for_update()
            )
            self.repo.metadata.update_value_by_key(model_cls, foreign_model, DOCLING_DOCUMENTS_METADATA_KEY, merge)
        return changed

    def delete_document_by_attachment_uid(
        self, model_cls: type[BaseMetadataModel], foreign_model: BaseDbModel, attachment_uid: str
    ) -> None:
        with DbSession.atomic() as db:
            db.exec(
                SqlBuilder.select.table(type(foreign_model))
                .where(type(foreign_model).column("id") == foreign_model.id)
                .with_for_update()
            )
            documents = [
                document
                for document in self.load_documents(model_cls, foreign_model)
                if document.get("attachment_uid") != attachment_uid
            ]
            self.save_documents(model_cls, foreign_model, documents)

    def publish_update(
        self, model_cls: type[BaseMetadataModel], foreign_model: BaseDbModel, topic: SocketTopic
    ) -> None:
        # Publish the committed state, never a lagging replica's prior progress.
        metadata = self.repo.metadata.get_by_key(
            model_cls, foreign_model, DOCLING_DOCUMENTS_METADATA_KEY, readonly=False
        )
        topic_uid = foreign_model.get_uid()
        if metadata:
            MetadataPublisher.updated_metadata(topic, topic_uid, DOCLING_DOCUMENTS_METADATA_KEY, metadata.value)
            return

        MetadataPublisher.deleted_metadata(topic, topic_uid, [DOCLING_DOCUMENTS_METADATA_KEY])

    def _load_metadata(self, model_cls: type[BaseMetadataModel], foreign_model: BaseDbModel) -> dict[str, str]:
        metadata = self.repo.metadata.get_by_key(model_cls, foreign_model, DOCLING_DOCUMENTS_METADATA_KEY)
        return {metadata.key: metadata.value} if metadata else {}
