from ..core.publisher import BaseSocketPublisher, SocketPublishModel
from ..core.routing import SocketTopic
from ..core.utils.decorators import staticclass
from ..domain.models import Bot, Card, CardComment, Project, User


@staticclass
class CardCommentPublisher(BaseSocketPublisher):
    @staticmethod
    def created(user_or_bot: User | Bot, project: Project, card: Card, comment: CardComment):
        api_comment = comment.api_response()
        author_key = "user" if isinstance(user_or_bot, User) else "bot"
        api_comment[author_key] = user_or_bot.api_response()
        api_comment["reactions"] = {}

        model = {"comment": api_comment}
        publish_model = SocketPublishModel(
            card_uids=[card.get_uid()],
            topic=SocketTopic.Board,
            topic_id=project.get_uid(),
            event=f"board:card:comment:added:{card.get_uid()}",
            data_keys=list(model.keys()),
        )

        CardCommentPublisher.put_dispather(model, publish_model)

    @staticmethod
    def updated(project: Project, card: Card, comment: CardComment):
        model = {
            "content": comment.content.model_dump() if comment.content else {"content": ""},
            "card_uid": card.get_uid(),
            "uid": comment.get_uid(),
            "updated_at": comment.updated_at,
        }
        publish_model = SocketPublishModel(
            card_uids=[card.get_uid()],
            topic=SocketTopic.Board,
            topic_id=project.get_uid(),
            event=f"board:card:comment:updated:{card.get_uid()}",
            data_keys=list(model.keys()),
        )

        CardCommentPublisher.put_dispather(model, publish_model)

    @staticmethod
    def deleted(project: Project, card: Card, comment: CardComment):
        model = {"card_uid": card.get_uid(), "comment_uid": comment.get_uid()}
        publish_model = SocketPublishModel(
            card_uids=[card.get_uid()],
            topic=SocketTopic.Board,
            topic_id=project.get_uid(),
            event=f"board:card:comment:deleted:{card.get_uid()}",
            data_keys=list(model.keys()),
        )

        CardCommentPublisher.put_dispather(model, publish_model)

    @staticmethod
    def reacted(
        user_or_bot: User | Bot,
        project: Project,
        card: Card,
        comment: CardComment,
        reaction: str,
        is_reacted: bool,
    ):
        author_key = "user_uid" if isinstance(user_or_bot, User) else "bot_uid"
        model = {
            "comment_uid": comment.get_uid(),
            "reaction": reaction,
            "is_reacted": is_reacted,
            author_key: user_or_bot.get_uid(),
        }

        publish_model = SocketPublishModel(
            card_uids=[card.get_uid()],
            topic=SocketTopic.Board,
            topic_id=project.get_uid(),
            event=f"board:card:comment:reacted:{card.get_uid()}",
            data_keys=list(model.keys()),
        )

        CardCommentPublisher.put_dispather(model, publish_model)
