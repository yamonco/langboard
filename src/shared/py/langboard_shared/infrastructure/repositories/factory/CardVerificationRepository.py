from sqlalchemy import func, select
from ....core.db import DbSession, SqlBuilder
from ....core.domain import BaseRepository
from ....domain.models.CardVerificationRecord import CardVerificationRecord


class CardVerificationRepository(BaseRepository[CardVerificationRecord]):
    @staticmethod
    def model_cls():
        return CardVerificationRecord

    @staticmethod
    def name() -> str:
        return "card_verification"

    def get_latest_by_card_ids(self, card_ids: list[int]) -> dict[int, CardVerificationRecord]:
        if not card_ids:
            return {}
        latest = (
            select(func.max(CardVerificationRecord.column("id")).label("latest_id"))
            .where(CardVerificationRecord.column("card_id").in_(card_ids))
            .group_by(CardVerificationRecord.column("card_id"))
            .subquery()
        )
        query = SqlBuilder.select.table(CardVerificationRecord).join(
            latest, CardVerificationRecord.column("id") == latest.c.latest_id
        )
        with DbSession.use(readonly=True) as db:
            return {record.card_id: record for record in db.exec(query).all()}
