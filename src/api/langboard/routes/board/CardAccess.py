"""Current card visibility and primary child provenance for direct REST routes."""

from fastapi import Request
from langboard_shared.core.db import DbSession, SqlBuilder
from langboard_shared.core.routing import ApiErrorCode, ApiException
from langboard_shared.core.security.CollaborationChannel import CollaborationChannel
from langboard_shared.domain.models import Bot, Card, CardAttachment, CardComment, Checkitem, Checklist, User
from langboard_shared.domain.services import DomainService
from langboard_shared.helpers import InfraHelper


def require_visible_card(
    project_uid: str, card_uid: str, request: Request,
    user_or_bot: User | Bot, service: DomainService,
) -> Card:
    """Keep action permissions while hiding unreadable card IDs before dispatch."""
    resolved = service.card.resolve_readable_card(
        project_uid, card_uid, user_or_bot,
        request.scope.get("collaboration_channel", CollaborationChannel.Api),
    )
    if resolved is None:
        raise ApiException.NotFound_404(ApiErrorCode.NF2003)
    return resolved[1]


def require_card_child(card: Card, model: type[CardComment | CardAttachment | Checklist | Checkitem], uid: str) -> None:
    """Reject foreign/deleted children before ownership or timer checks disclose state."""
    query = SqlBuilder.select.table(model).where(model.id == InfraHelper.convert_id(uid), model.deleted_at.is_(None))
    if model is Checkitem:
        query = query.join(Checklist, Checklist.id == Checkitem.checklist_id).where(
            Checklist.card_id == card.id, Checklist.deleted_at.is_(None),
        )
    else:
        query = query.where(model.card_id == card.id)
    with DbSession.use(readonly=False) as db:
        child = db.exec(query).first()
    if child is None:
        raise ApiException.NotFound_404(ApiErrorCode.NF2003)
