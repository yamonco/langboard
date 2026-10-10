from ....core.db import DbSession, SqlBuilder
from ....core.domain import BaseRepository
from ....core.types.ParamTypes import TCardParam
from ....domain.models import CardContentBlock
from ....helpers import InfraHelper


class CardContentBlockRepository(BaseRepository[CardContentBlock]):
    @staticmethod
    def model_cls():
        return CardContentBlock

    @staticmethod
    def name() -> str:
        return "card_content_block"

    def get_all_by_card(self, card: TCardParam) -> list[CardContentBlock]:
        """Ordered blocks of one card."""

        card_id = InfraHelper.convert_id(card)
        with DbSession.use(readonly=True) as db:
            return db.exec(
                SqlBuilder.select.table(CardContentBlock)
                .where(CardContentBlock.column("card_id") == card_id)
                .order_by(CardContentBlock.column("order").asc(), CardContentBlock.column("id").asc())
            ).all()

    def get_by_uid_card(self, block: TCardParam, card: TCardParam) -> CardContentBlock | None:
        """Resolve a block under its owning card (ancestry-checked)."""

        block_id = InfraHelper.convert_id(block)
        card_id = InfraHelper.convert_id(card)
        with DbSession.use(readonly=True) as db:
            return (
                db.exec(
                    SqlBuilder.select.table(CardContentBlock)
                    .where(
                        (CardContentBlock.column("id") == block_id)
                        & (CardContentBlock.column("card_id") == card_id)
                    )
                    .limit(1)
                ).first()
            )

    def renumber(self, card_id, ordered_ids: list) -> None:
        """Persist a new order for all blocks of a card."""

        for index, block_id in enumerate(ordered_ids):
            with DbSession.use(readonly=False) as db:
                db.exec(
                    SqlBuilder.update.table(CardContentBlock)
                    .values(order=index)
                    .where(
                        (CardContentBlock.column("id") == block_id)
                        & (CardContentBlock.column("card_id") == card_id)
                    )
                )
