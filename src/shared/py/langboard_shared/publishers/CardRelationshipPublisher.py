from typing import Any
from ..core.publisher import BaseSocketPublisher, SocketPublishModel
from ..core.routing import SocketTopic
from ..core.utils.decorators import staticclass
from ..domain.models import Card, Project


@staticclass
class CardRelationshipPublisher(BaseSocketPublisher):
    @staticmethod
    def updated(project: Project, card: Card, relationships: list[dict[str, Any]]):
        model = {
            "card_uid": card.get_uid(),
            "relationships": relationships,
        }
        publish_model = SocketPublishModel(
            card_uids=[card.get_uid()],
            topic=SocketTopic.Board,
            topic_id=project.get_uid(),
            event=f"board:card:relationships:updated:{project.get_uid()}",
            data_keys=list(model.keys()),
        )

        CardRelationshipPublisher.put_dispather(model, publish_model)
