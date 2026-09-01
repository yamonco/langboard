from typing import Any
from ....core.db import EditorContentModel
from ....core.domain import BaseDomainService
from ....core.types import SafeDateTime
from ....core.types.ParamTypes import TCardParam, TCommentParam, TProjectParam, TUserOrBot
from ....helpers import InfraHelper
from ....publishers import CardCommentPublisher
from ....tasks.activities import CardCommentActivityTask
from ....tasks.bots import CardCommentBotTask
from ...models import Bot, Card, CardComment, CardCommentReaction, Project, User
from .NotificationService import NotificationService
from .ReactionService import ReactionService


class CardCommentService(BaseDomainService):
    @staticmethod
    def name() -> str:
        """DO NOT EDIT THIS METHOD"""
        return "card_comment"

    def get_by_id_like(self, comment: TCommentParam | None) -> CardComment | None:
        comment = InfraHelper.get_by_id_like(CardComment, comment)
        return comment

    @staticmethod
    def can_mutate(user_or_bot: TUserOrBot, comment: CardComment) -> bool:
        """Return whether the actor owns the comment or is an administrator."""

        if isinstance(user_or_bot, User):
            return comment.user_id == user_or_bot.id or user_or_bot.is_admin
        return isinstance(user_or_bot, Bot) and comment.bot_id == user_or_bot.id

    def get_api_list_by_card(self, card: TCardParam | None) -> list[dict[str, Any]]:
        card = InfraHelper.get_by_id_like(Card, card)
        if not card:
            return []
        raw_comments = self.repo.card_comment.get_list_by_card(card)

        reaction_service = self._get_service(ReactionService)
        reactions = reaction_service.get_api_map(CardCommentReaction, [comment.id for comment, _, _ in raw_comments])

        comments = []
        for raw_comment in raw_comments:
            api_comment = self.convert_to_api_response(raw_comment, reactions.get(raw_comment[0].id))
            if api_comment:
                comments.append(api_comment)

        return comments

    def get_api_page_by_card(
        self,
        card: TCardParam | None,
        limit: int,
        before_created_at: SafeDateTime | None = None,
        before_comment: TCommentParam | None = None,
    ) -> tuple[list[dict[str, Any]], int, tuple[str, str] | None]:
        """Return a bounded newest-first page, total count, and next cursor fields."""

        card = InfraHelper.get_by_id_like(Card, card)
        if not card:
            return [], 0, None
        raw_comments = self.repo.card_comment.get_page_by_card(card, limit, before_created_at, before_comment)
        has_more = len(raw_comments) > limit
        page = raw_comments[:limit]

        reaction_service = self._get_service(ReactionService)
        reactions = reaction_service.get_api_map(CardCommentReaction, [comment.id for comment, _, _ in page])
        comments = [
            api_comment
            for comment, user, bot in page
            if (api_comment := self.convert_to_api_response((comment, user, bot), reactions.get(comment.id))) is not None
        ]
        next_fields = None
        if has_more and page:
            last_comment = page[-1][0]
            next_fields = (last_comment.created_at.isoformat(), last_comment.get_uid())
        return comments, self.repo.card_comment.count_by_card(card), next_fields

    def get_as_api(self, card: TCardParam | None, comment: TCommentParam | None) -> dict[str, Any] | None:
        if not comment:
            return None
        card = InfraHelper.get_by_id_like(Card, card)
        if not card:
            return None
        comment_id = InfraHelper.convert_id(comment)
        raw_comment = self.repo.card_comment.get_one(card, comment_id)
        if not raw_comment:
            return None

        reaction_service = self._get_service(ReactionService)
        reactions = reaction_service.get_api_map(CardCommentReaction, [comment_id])

        return self.convert_to_api_response(raw_comment, reactions.get(raw_comment[0].id))

    def convert_to_api_response(
        self, result: tuple[CardComment, User, Bot], reaction: dict[str, list[str]] | None = None
    ) -> dict[str, Any] | None:
        comment, user, bot = result
        if comment.deleted_at is not None:
            return None
        api_comment = comment.api_response()
        if user:
            api_comment["user"] = user.api_response()
        else:
            api_comment["bot"] = bot.api_response()
        api_comment["reactions"] = reaction or {}
        return api_comment

    def create(
        self,
        user_or_bot: TUserOrBot,
        project: TProjectParam | None,
        card: TCardParam | None,
        content: EditorContentModel | dict[str, Any],
    ) -> CardComment | None:
        params = InfraHelper.get_records_with_foreign_by_params((Project, project), (Card, card))
        if not params:
            return None
        project, card = params

        if isinstance(content, dict):
            content = EditorContentModel(**content)

        comment_params = {
            "card_id": card.id,
            "content": content,
        }

        if isinstance(user_or_bot, User):
            comment_params["user_id"] = user_or_bot.id
        else:
            comment_params["bot_id"] = user_or_bot.id

        comment = CardComment(**comment_params)
        self.repo.card_comment.insert(comment)

        CardCommentPublisher.created(user_or_bot, project, card, comment)

        notification_service = self._get_service(NotificationService)
        notification_service.notify_mentioned_in_comment(user_or_bot, project, card, comment)

        CardCommentActivityTask.card_comment_added(user_or_bot, project, card, comment)
        CardCommentBotTask.card_comment_added(user_or_bot, project, card, comment)

        return comment

    def update(
        self,
        user_or_bot: TUserOrBot,
        project: TProjectParam | None,
        card: TCardParam | None,
        comment: TCommentParam | None,
        content: EditorContentModel | dict[str, Any],
    ) -> CardComment | None:
        params = InfraHelper.get_records_with_foreign_by_params(
            (Project, project), (Card, card), (CardComment, comment)
        )
        if not params:
            return None
        project, card, comment = params
        if not self.can_mutate(user_or_bot, comment):
            return None

        if isinstance(content, dict):
            content = EditorContentModel(**content)

        old_content = comment.content
        comment.content = content
        self.repo.card_comment.update(comment)

        CardCommentPublisher.updated(project, card, comment)

        notification_service = self._get_service(NotificationService)
        notification_service.notify_mentioned_in_comment(user_or_bot, project, card, comment)

        CardCommentActivityTask.card_comment_updated(user_or_bot, project, card, old_content, comment)
        CardCommentBotTask.card_comment_updated(user_or_bot, project, card, comment)

        return comment

    def delete(
        self,
        user_or_bot: TUserOrBot,
        project: TProjectParam | None,
        card: TCardParam | None,
        comment: TCommentParam | None,
    ) -> CardComment | None:
        params = InfraHelper.get_records_with_foreign_by_params(
            (Project, project), (Card, card), (CardComment, comment)
        )
        if not params:
            return None
        project, card, comment = params
        if not self.can_mutate(user_or_bot, comment):
            return None

        self.repo.card_comment.delete(comment)

        CardCommentPublisher.deleted(project, card, comment)
        CardCommentActivityTask.card_comment_deleted(user_or_bot, project, card, comment)
        CardCommentBotTask.card_comment_deleted(user_or_bot, project, card, comment)

        return comment

    def toggle_reaction(
        self,
        user_or_bot: TUserOrBot,
        project: TProjectParam | None,
        card: TCardParam | None,
        comment: TCommentParam | None,
        reaction: str,
    ) -> bool | None:
        params = InfraHelper.get_records_with_foreign_by_params(
            (Project, project), (Card, card), (CardComment, comment)
        )
        if not params:
            return None
        project, card, comment = params

        reaction_service = self._get_service(ReactionService)
        is_reacted = reaction_service.toggle(user_or_bot, CardCommentReaction, comment.id, reaction)

        CardCommentPublisher.reacted(user_or_bot, project, card, comment, reaction, is_reacted)

        if is_reacted and comment.user_id:
            notification_service = self._get_service(NotificationService)
            notification_service.notify_reacted_to_comment(user_or_bot, project, card, comment, reaction)

        if is_reacted:
            CardCommentActivityTask.card_comment_reacted(user_or_bot, project, card, comment, reaction)
            CardCommentBotTask.card_comment_reacted(user_or_bot, project, card, comment, reaction)
        else:
            CardCommentActivityTask.card_comment_unreacted(user_or_bot, project, card, comment, reaction)
            CardCommentBotTask.card_comment_unreacted(user_or_bot, project, card, comment, reaction)

        return is_reacted
