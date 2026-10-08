from ..core.publisher import BaseSocketPublisher, SocketPublishModel
from ..core.routing import SocketTopic
from ..core.utils.decorators import staticclass
from ..domain.models import Card, CardAttachment, User


@staticclass
class CardAttachmentPublisher(BaseSocketPublisher):
    @staticmethod
    def uploaded(user: User, card: Card, card_attachment: CardAttachment):
        model = {
            "attachment": {
                **card_attachment.api_response(),
                "user": user.api_response(),
                "card_uid": card.get_uid(),
            }
        }

        publish_model = SocketPublishModel(
            card_uids=[card.get_uid()],
            topic=SocketTopic.BoardCard,
            topic_id=card.get_uid(),
            event=f"board:card:attachment:uploaded:{card.get_uid()}",
            data_keys=list(model.keys()),
        )

        CardAttachmentPublisher.put_dispather(model, publish_model)

    @staticmethod
    def order_changed(card: Card, card_attachment: CardAttachment):
        model = {"uid": card_attachment.get_uid(), "order": card_attachment.order}
        publish_model = SocketPublishModel(
            card_uids=[card.get_uid()],
            topic=SocketTopic.BoardCard,
            topic_id=card.get_uid(),
            event="board:card:attachment:order:changed",
            data_keys=list(model.keys()),
        )

        CardAttachmentPublisher.put_dispather(model, publish_model)

    @staticmethod
    def name_changed(card: Card, card_attachment: CardAttachment):
        model = {"name": card_attachment.filename}
        publish_model = SocketPublishModel(
            card_uids=[card.get_uid()],
            topic=SocketTopic.BoardCard,
            topic_id=card.get_uid(),
            event=f"board:card:attachment:name:changed:{card_attachment.get_uid()}",
            data_keys=list(model.keys()),
        )

        CardAttachmentPublisher.put_dispather(model, publish_model)

    @staticmethod
    def deleted(card: Card, card_attachment: CardAttachment):
        model = {"uid": card_attachment.get_uid()}
        publish_model = SocketPublishModel(
            card_uids=[card.get_uid()],
            topic=SocketTopic.BoardCard,
            topic_id=card.get_uid(),
            event="board:card:attachment:deleted",
            data_keys=list(model.keys()),
        )

        CardAttachmentPublisher.put_dispather(model, publish_model)
