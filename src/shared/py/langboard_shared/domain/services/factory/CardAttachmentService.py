from json import dumps, loads
from typing import Any
from uuid import uuid4
from sqlalchemy import Text, cast, func, literal_column
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from ....core.broker import Broker
from ....core.broker.TaskParameters import TaskParameters
from ....core.db import DbSession, SqlBuilder
from ....core.db.DbEngine import DbEngine
from ....core.domain import BaseDomainService
from ....core.routing import SocketTopic
from ....core.storage import FileModel
from ....core.types.ParamTypes import TAttachmentParam, TCardParam, TProjectParam
from ....helpers import InfraHelper
from ....publishers import CardAttachmentPublisher
from ....tasks.activities import CardAttachmentActivityTask
from ....tasks.bots import CardAttachmentBotTask
from ...models import Bot, Card, CardAttachment, CardMetadata, Project, User
from ..CardAppMutation import guard_card_app_mutation
from .DoclingMetadataService import DoclingMetadataService
from .InternalBotService import InternalBotService


DOCLING_INDEX_CARD_ATTACHMENT_TASK = "langboard_shared.tasks.docling.DoclingMetadataTask.index_card_attachment"


class CardAttachmentService(BaseDomainService):
    @staticmethod
    def name() -> str:
        """DO NOT EDIT THIS METHOD"""
        return "card_attachment"

    def _mark_card_changed_for_unread(self, card, target_type: str, target_id=None) -> None:
        """Stamp the unread cursor for this card change (lazy import avoids cycles)."""
        from .CardService import CardService

        card_service = self._get_service(CardService)
        card_service.mark_card_changed(card, target_type, target_id)

    def get_by_id_like(self, attachment: TAttachmentParam | None, *, consistent: bool = False) -> CardAttachment | None:
        if consistent:
            if attachment is None:
                return None
            with DbSession.use(readonly=False) as db:
                return db.exec(SqlBuilder.select.table(CardAttachment).where(CardAttachment.id == InfraHelper.convert_id(attachment))).first()
        attachment = InfraHelper.get_by_id_like(CardAttachment, attachment)
        return attachment

    def resolve_file_owner(self, storage_type: str, storage_name: str, filename: str) -> CardAttachment | None:
        """Find exact committed provenance, rejecting orphaned or ambiguous objects."""
        dialect = DbEngine.get_main_engine().dialect.name
        column = CardAttachment.column("file")
        if dialect == "postgresql":
            decoded = cast(cast(column, JSONB).op("#>>")(cast([], ARRAY(Text))), JSONB)
            def value(key):
                return decoded.op("->>")(literal_column(f"'{key}'"))
        elif dialect == "sqlite":
            def value(key):
                return func.json_extract(func.json_extract(column, literal_column("'$'")), literal_column(f"'$.{key}'"))
        elif dialect in {"mysql", "mariadb"}:
            def value(key):
                return func.json_unquote(func.json_extract(func.json_unquote(column), f"$.{key}"))
        else:
            raise ValueError("Unsupported database dialect for file provenance")
        with DbSession.use(readonly=False) as db:
            matches = db.exec(SqlBuilder.select.table(CardAttachment).where(
                value("storage_type") == storage_type,
                value("storage_name") == storage_name,
                value("filename") == filename,
            ).limit(2)).all()
        return matches[0] if len(matches) == 1 else None

    def get_api_list_by_card(self, card: TCardParam | None, limit: int | None = None) -> list[dict[str, Any]]:
        """Return attachment metadata, optionally enforcing a repository row limit."""

        card = InfraHelper.get_by_id_like(Card, card)
        if not card:
            return []
        card_attachments = self.repo.card_attachment.get_list_by_card(card, limit=limit)
        return [
            {**card_attachment.api_response(), "user": user.api_response()}
            for card_attachment, user in card_attachments
        ]

    @guard_card_app_mutation
    def create(
        self,
        user: User,
        project: TProjectParam | None,
        card: TCardParam | None,
        attachment: FileModel,
        *,
        dispatch_effects: bool = True,
    ) -> CardAttachment | None:
        params = InfraHelper.get_records_with_foreign_by_params((Project, project), (Card, card))
        if not params:
            return None
        project, card = params
        if card.is_linked_resource:
            return None

        card_attachment = CardAttachment(
            user_id=user.id,
            card_id=card.id,
            filename=attachment.original_filename,
            file=attachment,
            order=self.repo.card_attachment.get_next_order(card),
        )

        self.repo.card_attachment.insert(card_attachment)
        self._mark_card_changed_for_unread(card, "attachment", card_attachment.id)
        if dispatch_effects:
            self.dispatch_created(user, project, card, card_attachment)

        return card_attachment

    def dispatch_created(
        self,
        user: User,
        project: Project,
        card: Card,
        card_attachment: CardAttachment,
        *,
        include_bot: bool = True,
        include_document_processing: bool = True,
    ) -> None:
        """Dispatch effects after a persisted attachment is available."""
        docling_metadata = self._get_service(DoclingMetadataService)
        internal_bot = self._get_service(InternalBotService)
        binding = (
            internal_bot.get_document_vision_binding()
            if include_document_processing and docling_metadata.detect_document_type(card_attachment.filename)
            else None
        )
        vision_config = None
        if binding and internal_bot.is_document_processing_enabled():
            config = loads(binding.value)
            vision_config = {
                "binding_uid": binding.get_uid(),
                **{
                    key: config[key]
                    for key in ("base_url", "model_name", "model", "reasoning_effort", "top_p", "keyword_languages")
                    if key in config
                },
            }
        if vision_config and docling_metadata.queue_document(
            CardMetadata,
            card,
            card_attachment.get_uid(),
            card_attachment.filename,
            vision_config=vision_config,
            embedding_config=self._snapshot_embedding_config(),
        ):
            docling_metadata.publish_update(CardMetadata, card, SocketTopic.BoardCard)
            self._queue_docling_index_task(card_attachment)

        CardAttachmentPublisher.uploaded(user, card, card_attachment)
        CardAttachmentActivityTask.card_attachment_uploaded(user, project, card, card_attachment)
        if include_bot:
            CardAttachmentBotTask.card_attachment_uploaded(user, project, card, card_attachment)

    def _snapshot_embedding_config(self) -> dict | None:
        from ....tasks.docling.DocumentEmbedding import snapshot_embedding_config

        binding = self._get_service(InternalBotService).get_document_embedding_binding()
        if not binding:
            return None
        try:
            return snapshot_embedding_config(binding.value, binding.get_uid())
        except (ValueError, TypeError):
            # Invalid optional embedding configuration must not break attachment storage/transcription.
            return None

    @guard_card_app_mutation
    def request_document_processing(
        self, project: TProjectParam, card: TCardParam, attachment: TAttachmentParam, *, user: User | Bot, reprocess: bool = False
    ) -> str | None:
        """Explicit per-attachment processing; never scan existing files on settings changes."""
        params = InfraHelper.get_records_with_foreign_by_params(
            (Project, project), (Card, card), (CardAttachment, attachment)
        )
        if not params:
            return None
        project, card, attachment = params
        if (
            card.project_id != project.id
            or attachment.card_id != card.id
            or attachment.deleted_at is not None
            or card.is_linked_resource
        ):
            return None
        binding = self._get_service(InternalBotService).get_document_vision_binding()
        if not binding:
            raise ValueError("Configure a document vision provider before processing attachments")
        config = loads(binding.value)
        vision_config = {
            "binding_uid": binding.get_uid(),
            **{
                key: config[key]
                for key in ("base_url", "model_name", "model", "reasoning_effort", "top_p", "keyword_languages")
                if key in config
            },
        }
        docling = self._get_service(DoclingMetadataService)
        if not docling.detect_document_type(attachment.filename):
            raise ValueError("Attachment format does not support document processing")
        if docling.queue_document(
            CardMetadata,
            card,
            attachment.get_uid(),
            attachment.filename,
            vision_config=vision_config,
            embedding_config=self._snapshot_embedding_config(),
            force=reprocess,
        ):
            docling.publish_update(CardMetadata, card, SocketTopic.BoardCard)
            self._queue_docling_index_task(attachment)
        document = docling.get_document_by_attachment_uid(CardMetadata, card, attachment.get_uid())
        return document.get("status", "pending") if document else None

    @guard_card_app_mutation
    def request_document_embedding(
        self, project: TProjectParam, card: TCardParam, attachment: TAttachmentParam, *, user: User | Bot
    ) -> str | None:
        """Explicitly embed one existing transcription without rerunning VLM or scanning files."""
        from ....tasks.docling.DocumentEmbedding import snapshot_embedding_config

        params = InfraHelper.get_records_with_foreign_by_params(
            (Project, project), (Card, card), (CardAttachment, attachment)
        )
        if not params:
            return None
        project, card, attachment = params
        if (
            card.project_id != project.id
            or attachment.card_id != card.id
            or attachment.deleted_at is not None
            or card.is_linked_resource
        ):
            return None
        binding = self._get_service(InternalBotService).get_document_embedding_binding()
        if not binding:
            raise ValueError("Configure an embedding provider before indexing attachments")
        snapshot = snapshot_embedding_config(binding.value, binding.get_uid(), explicit=True)
        metadata = self._get_service(DoclingMetadataService)
        document = metadata.get_document_by_attachment_uid(CardMetadata, card, attachment.get_uid())
        if not document or document.get("status") != "indexed" or not document.get("content_hash"):
            raise ValueError("Process this attachment before requesting embeddings")
        old = document.get("embedding") or {}
        request_uid = uuid4().hex
        queued = {**old, "status": "pending", "request_uid": request_uid}
        if old.get("pointer") and "config" not in queued and document.get("embedding_config"):
            queued["config"] = document["embedding_config"]
        queued.pop("error", None)
        args, kwargs = TaskParameters(
            dumps(
                {
                    "attachment_uid": attachment.get_uid(),
                    "generation": document["generation"],
                    "request_uid": request_uid,
                }
            )
        ).pack()

        def enqueue():
            try:
                Broker.celery.send_task(
                    "langboard_shared.tasks.docling.DocumentEmbeddingTask.index_transcribed_attachment",
                    args=args,
                    kwargs=kwargs,
                    time_limit=600,
                    soft_time_limit=570,
                )
            except Exception:
                metadata.publish_document_embedding(
                    card,
                    attachment.get_uid(),
                    document["generation"],
                    document["content_hash"],
                    {**queued, "status": "failed", "error": "Embedding queue unavailable; request indexing again"},
                    expected_embedding=queued,
                )
            metadata.publish_update(CardMetadata, card, SocketTopic.BoardCard)

        with DbSession.atomic() as db:
            if not metadata.publish_document_embedding(
                card,
                attachment.get_uid(),
                document["generation"],
                document["content_hash"],
                queued,
                expected_embedding=old,
                embedding_config=snapshot,
            ):
                raise ValueError("Attachment changed; read its current state before retrying")
            db.after_commit(enqueue)
        return "pending"

    @guard_card_app_mutation
    def change_order(
        self,
        project: TProjectParam | None,
        card: TCardParam | None,
        card_attachment: TAttachmentParam | None,
        order: int,
        *,
        user: User | Bot,
    ) -> bool | None:
        params = InfraHelper.get_records_with_foreign_by_params(
            (Project, project), (Card, card), (CardAttachment, card_attachment)
        )
        if not params:
            return None
        project, card, card_attachment = params

        old_order = card_attachment.order
        card_attachment.order = order
        self.repo.card_attachment.update_column_order(card_attachment, card, old_order, order)

        CardAttachmentPublisher.order_changed(card, card_attachment)

        return True

    @guard_card_app_mutation
    def change_name(
        self,
        user: User,
        project: TProjectParam | None,
        card: TCardParam | None,
        card_attachment: TAttachmentParam | None,
        name: str,
    ) -> bool | None:
        params = InfraHelper.get_records_with_foreign_by_params(
            (Project, project), (Card, card), (CardAttachment, card_attachment)
        )
        if not params:
            return None
        project, card, card_attachment = params

        old_name = card_attachment.filename
        card_attachment.filename = name

        self.repo.card_attachment.update(card_attachment)

        CardAttachmentPublisher.name_changed(card, card_attachment)
        self._mark_card_changed_for_unread(card, "attachment", card_attachment.id)
        CardAttachmentActivityTask.card_attachment_name_changed(user, project, card, old_name, card_attachment)
        CardAttachmentBotTask.card_attachment_name_changed(user, project, card, card_attachment)

        return True

    @guard_card_app_mutation
    def delete(
        self,
        user: User,
        project: TProjectParam | None,
        card: TCardParam | None,
        card_attachment: TAttachmentParam | None,
    ) -> bool | None:
        params = InfraHelper.get_records_with_foreign_by_params(
            (Project, project), (Card, card), (CardAttachment, card_attachment)
        )
        if not params:
            return None
        project, card, card_attachment = params

        docling_metadata = self._get_service(DoclingMetadataService)
        with DbSession.atomic() as db:
            document = docling_metadata.delete_document_by_attachment_uid(CardMetadata, card, card_attachment.get_uid())
            pointer = ((document or {}).get("embedding") or {}).get("pointer")
            self.repo.card_attachment.delete(card_attachment)
            self.repo.card_attachment.reoder_after_delete(card, card_attachment.order)
            if isinstance(pointer, dict):
                args, kwargs = TaskParameters(dumps(pointer)).pack()
                db.after_commit(
                    lambda: Broker.celery.send_task(
                        "langboard_shared.tasks.docling.DocumentEmbeddingTask.remove_attachment_embedding",
                        args=args,
                        kwargs=kwargs,
                    )
                )
        docling_metadata.publish_update(CardMetadata, card, SocketTopic.BoardCard)

        CardAttachmentPublisher.deleted(card, card_attachment)
        self._mark_card_changed_for_unread(card, "attachment")
        CardAttachmentActivityTask.card_attachment_deleted(user, project, card, card_attachment)
        CardAttachmentBotTask.card_attachment_deleted(user, project, card, card_attachment)

        return True

    def _queue_docling_index_task(self, card_attachment: CardAttachment) -> None:
        document = self._get_service(DoclingMetadataService).get_document_by_attachment_uid(
            CardMetadata, InfraHelper.get_by_id_like(Card, card_attachment.card_id), card_attachment.get_uid()
        )
        args, kwargs = TaskParameters(
            dumps(
                {
                    "attachment_uid": card_attachment.get_uid(),
                    "generation": document.get("generation") if document else None,
                }
            )
        ).pack()
        # Native transaction hook prevents queue delivery before the attachment commit.
        with DbSession.atomic() as db:
            db.after_commit(
                lambda: Broker.celery.send_task(DOCLING_INDEX_CARD_ATTACHMENT_TASK, args=args, kwargs=kwargs)
            )
