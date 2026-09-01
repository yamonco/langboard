import json
from enum import Enum
from hashlib import sha256
from pathlib import Path
from typing import Any
from ....core.db import BaseDbModel
from ....core.domain import BaseDomainService
from ....core.routing import SocketTopic
from ....core.types import SafeDateTime
from ....domain.models.bases import BaseMetadataModel
from ....publishers import MetadataPublisher


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
}


class DoclingIndexStatus(str, Enum):
    Pending = "pending"
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
        self, model_cls: type[BaseMetadataModel], foreign_model: BaseDbModel, attachment_uid: str, filename: str
    ) -> bool:
        document_type = self.detect_document_type(filename)
        if not document_type:
            return False

        document = {
            "attachment_uid": attachment_uid,
            "document_type": document_type,
            "status": DoclingIndexStatus.Pending.value,
            "content": {},
        }
        self.upsert_document(model_cls, foreign_model, document)
        return True

    def mark_document_indexed(
        self,
        model_cls: type[BaseMetadataModel],
        foreign_model: BaseDbModel,
        attachment_uid: str,
        document_type: str,
        content_hash: str | None = None,
        content: dict[str, Any] | None = None,
    ) -> bool:
        document = {
            "attachment_uid": attachment_uid,
            "document_type": document_type,
            "status": DoclingIndexStatus.Indexed.value,
            "content_hash": content_hash,
            "indexed_at": SafeDateTime.now().isoformat(),
            "content": content or {},
        }
        self.upsert_document(model_cls, foreign_model, document)
        return True

    def mark_document_failed(
        self,
        model_cls: type[BaseMetadataModel],
        foreign_model: BaseDbModel,
        attachment_uid: str,
        filename: str,
        error_message: str,
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
        self.upsert_document(model_cls, foreign_model, document)
        return True

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
        self, model_cls: type[BaseMetadataModel], foreign_model: BaseDbModel, document: dict[str, Any]
    ) -> None:
        attachment_uid = document["attachment_uid"]
        documents = [
            current
            for current in self.load_documents(model_cls, foreign_model)
            if current.get("attachment_uid") != attachment_uid
        ]
        documents.append(document)
        documents.sort(key=lambda current: str(current.get("document_type") or ""))
        self.save_documents(model_cls, foreign_model, documents)

    def delete_document_by_attachment_uid(
        self, model_cls: type[BaseMetadataModel], foreign_model: BaseDbModel, attachment_uid: str
    ) -> None:
        documents = [
            document
            for document in self.load_documents(model_cls, foreign_model)
            if document.get("attachment_uid") != attachment_uid
        ]
        self.save_documents(model_cls, foreign_model, documents)

    def publish_update(
        self, model_cls: type[BaseMetadataModel], foreign_model: BaseDbModel, topic: SocketTopic
    ) -> None:
        metadata = self.repo.metadata.get_by_key(model_cls, foreign_model, DOCLING_DOCUMENTS_METADATA_KEY)
        topic_uid = foreign_model.get_uid()
        if metadata:
            MetadataPublisher.updated_metadata(topic, topic_uid, DOCLING_DOCUMENTS_METADATA_KEY, metadata.value)
            return

        MetadataPublisher.deleted_metadata(topic, topic_uid, [DOCLING_DOCUMENTS_METADATA_KEY])

    def _load_metadata(self, model_cls: type[BaseMetadataModel], foreign_model: BaseDbModel) -> dict[str, str]:
        metadata = self.repo.metadata.get_by_key(model_cls, foreign_model, DOCLING_DOCUMENTS_METADATA_KEY)
        return {metadata.key: metadata.value} if metadata else {}
