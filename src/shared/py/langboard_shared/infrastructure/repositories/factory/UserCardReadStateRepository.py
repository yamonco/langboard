from ....core.db import DbSession, SqlBuilder
from ....core.domain import BaseRepository
from ....core.types import SafeDateTime, SnowflakeID
from ....core.types.ParamTypes import TCardParam, TUserParam
from ....domain.models import UserCardReadState
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

    def upsert_seen(self, user: TUserParam, card: TCardParam, seen_change_seq: int) -> UserCardReadState:
        """Advance one user's read cursor for a card; never regress it."""

        user_id = InfraHelper.convert_id(user)
        card_id = InfraHelper.convert_id(card)
        state = None
        with DbSession.use(readonly=True) as db:
            state = (
                db.exec(
                    SqlBuilder.select.table(UserCardReadState)
                    .where(
                        (UserCardReadState.column("user_id") == user_id)
                        & (UserCardReadState.column("card_id") == card_id)
                    )
                    .limit(1)
                ).first()
            )

        if state is None:
            state = UserCardReadState(
                user_id=user_id,
                card_id=card_id,
                seen_change_seq=seen_change_seq,
                seen_at=SafeDateTime.now(),
            )
            self.insert(state)
            return state

        if seen_change_seq <= state.seen_change_seq:
            return state
        state.seen_change_seq = seen_change_seq
        state.seen_at = SafeDateTime.now()
        self.update(state)
        return state
