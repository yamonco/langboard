"""Current readiness generation for an already authorized card batch.

This fence is not an agent lease or proof of running execution. A live card
without a generation row has generation zero, matching current_execution.
"""

from sqlalchemy import column, func, select, table
from ...core.db import DbSession


_GENERATIONS = table("card_execution_generation", column("card_id"), column("execution_generation"))
_CARDS = table("card", column("id"), column("deleted_at"))


def execution_generations(card_ids: list[int]) -> dict[int, int]:
    if not card_ids:
        return {}
    statement = (
        select(_CARDS.c.id, func.coalesce(_GENERATIONS.c.execution_generation, 0))
        .select_from(_CARDS.outerjoin(_GENERATIONS, _GENERATIONS.c.card_id == _CARDS.c.id))
        .where(_CARDS.c.id.in_(card_ids), _CARDS.c.deleted_at.is_(None))
    )
    # A replica may expose an old fence immediately after a readiness transition.
    with DbSession.use(readonly=False) as db:
        return {int(card_id): int(generation) for card_id, generation in db.exec(statement).all()}
