"""Pending native card approvals: no request payload or caller identity escapes."""

from sqlalchemy import or_, select, union_all
from ...core.db import DbSession
from ...core.types import SafeDateTime
from ...helpers import ModelHelper
from ..models import Card, GraphApprovalRequest
from ..models.bases import BaseGraphApprovalRequestModel
from ..models.GraphApprovalRequest import GraphApprovalStatus


def pending_card_approvals(card_ids: list[int]) -> dict[int, int]:
    """Read only approvals explicitly scoped to an already authorized card batch.

    No pending approval is not proof that other input/approval policies are clear.
    Expiry is projected without changing the approval record or resuming a graph.
    """
    if not card_ids:
        return {}
    now = SafeDateTime.now()
    queries = []
    for detail in ModelHelper.get_models_by_base_class(BaseGraphApprovalRequestModel):
        queries.append(
            select(detail.scope_id.label("card_id"), GraphApprovalRequest.id.label("approval_id"))
            .select_from(detail)
            .join(GraphApprovalRequest, GraphApprovalRequest.id == detail.approval_request_id)
            .join(Card, Card.id == detail.scope_id)
            .where(
                detail.scope_table == Card.__tablename__,
                detail.scope_id.in_(card_ids),
                Card.deleted_at.is_(None),
                GraphApprovalRequest.request_type == detail.get_request_type().value,
                GraphApprovalRequest.status == GraphApprovalStatus.Pending.value,
                or_(GraphApprovalRequest.expires_at.is_(None), GraphApprovalRequest.expires_at > now),
            )
        )
    if not queries:
        return {}
    statement = select(union_all(*queries).subquery()).distinct()
    # Approval resolution must be reflected immediately, even with a lagging replica.
    with DbSession.use(readonly=False) as db:
        rows = db.exec(statement).all()
    counts: dict[int, int] = {}
    for card_id, _ in rows:
        counts[int(card_id)] = counts.get(int(card_id), 0) + 1
    return counts
