"""Shared blocks-only prerequisite policy for reads and execution fences.

Callers supply already-authorized current-card IDs. Hidden prerequisite titles,
UIDs and linked-resource titles never leave this projection.
"""

from sqlalchemy import bindparam, select, text
from ...core.db import DbSession
from ...core.types import SnowflakeID
from ..DependencyConditions import BLOCKING_RELATION_JOINS, UNSATISFIED_PREREQUISITE


_VISIBLE_PREREQUISITE = """
    prerequisite.project_id = c.project_id AND prerequisite.deleted_at IS NULL
    AND prerequisite.source_type IS NULL
"""


def dependency_blockers(card_ids: list[int]) -> dict[int, list[dict]]:
    """Read all direct unsatisfied blocks in one permission-scoped batch."""
    if not card_ids:
        return {}
    query = (
        select(
            text("c.id"),
            text("r.id"),
            text(f"CASE WHEN {_VISIBLE_PREREQUISITE} THEN prerequisite.id ELSE NULL END"),
            text(f"CASE WHEN {_VISIBLE_PREREQUISITE} THEN prerequisite.title ELSE NULL END"),
        )
        .select_from(
            text("card c JOIN card_relationship r ON r.card_id_child = c.id " + BLOCKING_RELATION_JOINS)
        )
        .where(text("c.id IN :card_ids").bindparams(bindparam("card_ids", expanding=True)))
        .where(text(UNSATISFIED_PREREQUISITE))
        .order_by(text("c.id, r.id"))
    )
    with DbSession.use(readonly=False) as db:
        rows = db.exec(query, params={"card_ids": card_ids}).all()
    result: dict[int, list[dict]] = {int(card_id): [] for card_id in card_ids}
    for card_id, relationship_id, parent_id, title in rows:
        result[int(card_id)].append(
            {
                "relationship_uid": SnowflakeID(relationship_id).to_short_code(),
                "card_uid": SnowflakeID(parent_id).to_short_code() if parent_id is not None else None,
                "title": title if parent_id is not None else None,
                "accessible": parent_id is not None,
                "code": "dependency_unfinished" if parent_id is not None else "dependency_unavailable",
            }
        )
    return result
