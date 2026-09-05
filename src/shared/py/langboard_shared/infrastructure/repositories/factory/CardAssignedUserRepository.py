from typing import Any, Literal, cast, overload
from ....core.db import DbSession, SqlBuilder
from ....core.domain import BaseRepository
from ....core.types import SnowflakeID
from ....core.types.ParamTypes import TCardParam, TProjectParam
from ....domain.models import Card, CardAssignedUser, ProjectAssignedUser, User
from ....helpers import InfraHelper


class CardAssignedUserRepository(BaseRepository[CardAssignedUser]):
    @staticmethod
    def model_cls():
        return CardAssignedUser

    @staticmethod
    def name() -> str:
        return "card_assigned_user"

    def add_member(self, card: Card, member: ProjectAssignedUser) -> bool:
        """Add one member under the card lock without replacing other assignments."""
        with DbSession.use(readonly=False) as db:
            locked = db.exec(
                SqlBuilder.select.table(Card).where(Card.column("id") == card.id).with_for_update()
            ).first()
            if locked is None or locked.project_id != member.project_id:
                raise ValueError("Card and membership must belong to the same project")
            existing = db.exec(
                SqlBuilder.select.table(CardAssignedUser).where(
                    (CardAssignedUser.column("card_id") == card.id)
                    & (CardAssignedUser.column("user_id") == member.user_id)
                )
            ).first()
            if existing is not None:
                return False
            db.insert(CardAssignedUser(card_id=card.id, user_id=member.user_id, project_assigned_id=member.id))
        return True

    @overload
    def get_all_by_card(
        self, card: TCardParam, only_ids: Literal[False] = False, limit: int | None = None
    ) -> list[tuple[User, CardAssignedUser]]: ...
    @overload
    def get_all_by_card(
        self, card: TCardParam, only_ids: Literal[True], limit: int | None = None
    ) -> list[tuple[SnowflakeID, CardAssignedUser]]: ...
    def get_all_by_card(
        self, card: TCardParam, only_ids: bool = False, limit: int | None = None
    ) -> list[tuple[User, CardAssignedUser]] | list[tuple[SnowflakeID, CardAssignedUser]]:
        """Return assigned card users, optionally enforcing a database row limit."""

        card_id = InfraHelper.convert_id(card)

        raw_users = []
        if only_ids:
            query = SqlBuilder.select.columns(User.id, CardAssignedUser)
        else:
            query = SqlBuilder.select.tables(User, CardAssignedUser)
        query = (
            query.join(
                CardAssignedUser,
                User.column("id") == CardAssignedUser.column("user_id"),
            )
            .where(CardAssignedUser.column("card_id") == card_id)
            .order_by(CardAssignedUser.column("id").asc())
        )
        if limit is not None:
            query = query.limit(limit)
        with DbSession.use(readonly=True) as db:
            result = db.exec(query)
            raw_users = result.all()
        return cast(Any, raw_users)

    def get_all_by_project(self, project: TProjectParam) -> list[tuple[User, CardAssignedUser]]:
        project_id = InfraHelper.convert_id(project)

        raw_users = []
        with DbSession.use(readonly=True) as db:
            result = db.exec(
                SqlBuilder.select.tables(User, CardAssignedUser)
                .join(
                    CardAssignedUser,
                    User.column("id") == CardAssignedUser.column("user_id"),
                )
                .join(Card, CardAssignedUser.column("card_id") == Card.column("id"))
                .where(Card.column("project_id") == project_id)
            )
            raw_users = result.all()
        return raw_users

    def delete_all_by_card(self, card: TCardParam):
        card_id = InfraHelper.convert_id(card)

        with DbSession.use(readonly=False) as db:
            db.exec(SqlBuilder.delete.table(CardAssignedUser).where(CardAssignedUser.column("card_id") == card_id))
