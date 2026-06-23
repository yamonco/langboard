from typing import Any
from ....core.broker import Broker
from ....core.broker.TaskParameters import TaskParameters
from ....core.domain import BaseDomainService
from ....core.routing import SocketTopic
from ....core.storage import FileModel
from ....core.types.ParamTypes import TAttachmentParam, TCardParam, TProjectParam
from ....helpers import InfraHelper
from ....publishers import CardAttachmentPublisher
from ....tasks.activities import CardAttachmentActivityTask
from ....tasks.bots import CardAttachmentBotTask
from ...models import Card, CardAttachment, CardMetadata, Project, User
from .DoclingMetadataService import DoclingMetadataService


DOCLING_INDEX_CARD_ATTACHMENT_TASK = "langboard_shared.tasks.docling.DoclingMetadataTask.index_card_attachment"


class CardAttachmentService(BaseDomainService):
    @staticmethod
    def name() -> str:
        """DO NOT EDIT THIS METHOD"""
        return "card_attachment"

    def get_by_id_like(self, attachment: TAttachmentParam | None) -> CardAttachment | None:
        attachment = InfraHelper.get_by_id_like(CardAttachment, attachment)
        return attachment

    def get_api_list_by_card(self, card: TCardParam | None) -> list[dict[str, Any]]:
        card = InfraHelper.get_by_id_like(Card, card)
        if not card:
            return []
        card_attachments = self.repo.card_attachment.get_list_by_card(card)
        return [
            {**card_attachment.api_response(), "user": user.api_response()}
            for card_attachment, user in card_attachments
        ]

    def create(
        self, user: User, project: TProjectParam | None, card: TCardParam | None, attachment: FileModel
    ) -> CardAttachment | None:
        params = InfraHelper.get_records_with_foreign_by_params((Project, project), (Card, card))
        if not params:
            return None
        project, card = params

        card_attachment = CardAttachment(
            user_id=user.id,
            card_id=card.id,
            filename=attachment.original_filename,
            file=attachment,
            order=self.repo.card_attachment.get_next_order(card),
        )

        self.repo.card_attachment.insert(card_attachment)
        docling_metadata = self._get_service(DoclingMetadataService)
        if docling_metadata.queue_document(CardMetadata, card, card_attachment.get_uid(), card_attachment.filename):
            docling_metadata.publish_update(CardMetadata, card, SocketTopic.BoardCard)
            self._queue_docling_index_task(card_attachment)

        CardAttachmentPublisher.uploaded(user, card, card_attachment)
        CardAttachmentActivityTask.card_attachment_uploaded(user, project, card, card_attachment)
        CardAttachmentBotTask.card_attachment_uploaded(user, project, card, card_attachment)

        return card_attachment

    def change_order(
        self,
        project: TProjectParam | None,
        card: TCardParam | None,
        card_attachment: TAttachmentParam | None,
        order: int,
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
        CardAttachmentActivityTask.card_attachment_name_changed(user, project, card, old_name, card_attachment)
        CardAttachmentBotTask.card_attachment_name_changed(user, project, card, card_attachment)

        return True

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
        docling_metadata.delete_document_by_attachment_uid(CardMetadata, card, card_attachment.get_uid())
        docling_metadata.publish_update(CardMetadata, card, SocketTopic.BoardCard)
        self.repo.card_attachment.delete(card_attachment)
        self.repo.card_attachment.reoder_after_delete(card, card_attachment.order)

        CardAttachmentPublisher.deleted(card, card_attachment)
        CardAttachmentActivityTask.card_attachment_deleted(user, project, card, card_attachment)
        CardAttachmentBotTask.card_attachment_deleted(user, project, card, card_attachment)

        return True

    def _queue_docling_index_task(self, card_attachment: CardAttachment) -> None:
        args, kwargs = TaskParameters(card_attachment).pack()
        Broker.celery.send_task(DOCLING_INDEX_CARD_ATTACHMENT_TASK, args=args, kwargs=kwargs)
