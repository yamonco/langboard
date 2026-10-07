"""Audience-scoped blocks projection; execution fences remain authoritative separately."""

from sqlalchemy import and_, bindparam, literal_column, or_, select, text
from ...core.db import DbSession
from ...core.types import SnowflakeID
from ..DependencyConditions import BLOCKING_RELATION_JOINS, UNSATISFIED_PREREQUISITE
from .CardVisibilityPolicy import CardVisibilityContext, card_visibility_scope


_VISIBLE_PREREQUISITE = """
    prerequisite.project_id = c.project_id AND prerequisite.deleted_at IS NULL
    AND prerequisite.source_type IS NULL
"""


def dependency_blockers(
    card_ids: list[int], *, context: CardVisibilityContext | None = None,
) -> dict[int, list[dict] | None]:
    """Project readable edges only; absent audience means unknown, never clear.

    Hidden edges contribute no identity, count or blocked-state hint. This
    projection cannot authorize execution: execution readiness evaluates
    UNSATISFIED_PREREQUISITE independently without this audience filter.
    """
    if not card_ids:
        return {}
    if context is None:
        return {int(card_id): None for card_id in card_ids}

    def columns(alias):
        return {key: literal_column(f"{alias}.{key}") for key in ("visibility", "owner_user_id")}

    current = columns("c")
    prerequisite = columns("prerequisite")
    query = (
        select(
            text("c.id"),
            text("r.id"),
            text("prerequisite.id"),
            text("prerequisite.title"),
        )
        .select_from(
            text("card c JOIN card_relationship r ON r.card_id_child = c.id " + BLOCKING_RELATION_JOINS)
        )
        .where(text("c.id IN :card_ids").bindparams(bindparam("card_ids", expanding=True)))
        .where(text(UNSATISFIED_PREREQUISITE))
        .where(text(_VISIBLE_PREREQUISITE))
        .where(text("c.deleted_at IS NULL"))
        .where(card_visibility_scope(context, columns=current))
        .where(card_visibility_scope(context, columns=prerequisite))
        .where(or_(
            and_(current["visibility"] != "PRIVATE", prerequisite["visibility"] != "PRIVATE"),
            and_(current["visibility"] == "PRIVATE", prerequisite["visibility"] == "PRIVATE",
                 current["owner_user_id"] == prerequisite["owner_user_id"]),
        ))
        .order_by(text("c.id, r.id"))
    )
    with DbSession.use(readonly=False) as db:
        rows = db.exec(query, params={"card_ids": card_ids}).all()
    result: dict[int, list[dict]] = {int(card_id): [] for card_id in card_ids}
    for card_id, relationship_id, parent_id, title in rows:
        result[int(card_id)].append(
            {
                "relationship_uid": SnowflakeID(relationship_id).to_short_code(),
                "card_uid": SnowflakeID(parent_id).to_short_code(),
                "title": title,
                "accessible": True,
                "code": "dependency_unfinished",
            }
        )
    return result
