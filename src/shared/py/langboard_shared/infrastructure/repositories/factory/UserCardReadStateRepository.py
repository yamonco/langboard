from ....core.db import DbSession, SqlBuilder
from ....core.domain import BaseRepository
from ....core.types import SafeDateTime, SnowflakeID
from ....core.types.ParamTypes import TCardParam, TUserParam
from ....domain.models import Card, ProjectAssignedUser, User, UserCardReadState
from ....helpers import InfraHelper


class UserCardReadStateRepository(BaseRepository[UserCardReadState]):
    @staticmethod
    def model_cls():
        return UserCardReadState

    @staticmethod
    def name() -> str:
        return "user_card_read_state"

    def get_seen_seq_map(self, user_id: SnowflakeID, card_ids: list[SnowflakeID]) -> dict[int, int]:
        """Return card_id -> seen_change_seq for one user's cards."""

        if not card_ids:
            return {}
        states = []
        with DbSession.use(readonly=True) as db:
            result = db.exec(
                SqlBuilder.select.table(UserCardReadState)
                .where((UserCardReadState.column("user_id") == user_id) & UserCardReadState.column("card_id").in_(card_ids))
            )
            states = result.all()
        return {state.card_id: state.seen_change_seq for state in states}

    def get_readers(self, card: Card) -> list[dict]:
        """Expose existing read receipts only for current board members."""
        with DbSession.use(readonly=True) as db:
            rows = db.exec(
                SqlBuilder.select.tables(UserCardReadState, User)
                .join(User, User.column("id") == UserCardReadState.column("user_id"))
                .join(ProjectAssignedUser, ProjectAssignedUser.column("user_id") == User.column("id"))
                .where(UserCardReadState.column("card_id") == card.id)
                .where(UserCardReadState.column("seen_change_seq") >= 0)
                .where(ProjectAssignedUser.column("project_id") == card.project_id)
            ).all()
        return [{"user_uid": user.get_uid(), "seen_at": state.seen_at.isoformat()} for state, user in rows]

    def set_read_state(self, user: TUserParam, card: Card, seen: bool) -> UserCardReadState:
        """Serialize receipt creation and unread changes on the existing card row.

        A negative cursor is an explicit unread override, including old cards
        below the board baseline. No separate acknowledgement state is created.
        """
        user_id = InfraHelper.convert_id(user)
        with DbSession.atomic() as db:
            db.exec(SqlBuilder.select.table(Card).where(Card.column("id") == card.id).with_for_update()).first()
            state = db.exec(
                SqlBuilder.select.table(UserCardReadState)
                .where(UserCardReadState.column("user_id") == user_id)
                .where(UserCardReadState.column("card_id") == card.id)
            ).first()
            cursor = card.last_change_seq if seen else -1
            if state is None:
                state = UserCardReadState(user_id=user_id, card_id=card.id, seen_change_seq=cursor, seen_at=SafeDateTime.now())
                db.insert(state)
            elif not seen or cursor > state.seen_change_seq:
                state.seen_change_seq = cursor
                state.seen_at = SafeDateTime.now()
                db.update(state)
        return state

    def upsert_seen(self, user: TUserParam, card: TCardParam, seen_change_seq: int) -> UserCardReadState:
        resolved = InfraHelper.get_by_id_like(Card, card)
        if resolved is None:
            raise ValueError("Card not found")
        return self.set_read_state(user, resolved, True)
