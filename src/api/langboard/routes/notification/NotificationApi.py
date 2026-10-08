from typing import Literal, cast
from fastapi import Depends, Request
from langboard_shared.core.db import DbSession
from langboard_shared.core.db.SqlBuilder import SqlBuilder
from langboard_shared.core.filter import AuthFilter
from langboard_shared.core.routing import AppRouter, JsonResponse
from langboard_shared.core.schema import OpenApiSchema
from langboard_shared.core.security import AuthSecurity
from langboard_shared.core.security.CollaborationChannel import CollaborationChannel
from langboard_shared.core.types import SnowflakeID
from langboard_shared.domain.models import User, UserNotification
from langboard_shared.domain.services import DomainService
from langboard_shared.security import Auth
from pydantic import BaseModel, Field
from .NotificationForm import NotificationForm


@AppRouter.api.get(
    "/notifications",
    tags=["Notification"],
    responses=OpenApiSchema().suc({"notifications": [UserNotification]}).auth().forbidden().get(),
)
@AuthFilter.add("user")
def toggle_all_notification_subscription(
    request: Request,
    form: NotificationForm = Depends(), user: User = Auth.scope("user"), service: DomainService = DomainService.scope()
) -> JsonResponse:
    if form.time_range not in ["3d", "7d", "1m", "all"]:
        form.time_range = "3d"
    notifications, has_more, unread_count = service.notification.get_api_list(
        user,
        cast(Literal["3d", "7d", "1m", "all"], form.time_range),
        form.page,
        form.limit,
        unread_only=form.unread_only,
        channel=request.scope.get("collaboration_channel", CollaborationChannel.Api),
    )
    return JsonResponse(content={"notifications": notifications, "has_more": has_more, "unread_count": unread_count})


@AppRouter.api.get("/notifications/{notification_uid}/dispatch-context", tags=["Notification"])
@AuthFilter.add("user")
def notification_dispatch_context(
    notification_uid: str, user: User = Auth.scope("user"), service: DomainService = DomainService.scope(),
) -> JsonResponse:
    try:
        notification_id = SnowflakeID.from_short_code(notification_uid)
    except (TypeError, ValueError):
        return JsonResponse(content={"allowed": False})
    context = service.notification.get_dispatch_context(user, notification_id)
    return JsonResponse(content={"allowed": context is not None, "recipient": context})


class SocketCardDispatchForm(BaseModel):
    card_uids: list[str] = Field(min_length=1, max_length=2)
    recipient_uids: list[str] = Field(max_length=100)


@AppRouter.api.post("/socket/card-dispatch-context", tags=["Notification"])
@AuthFilter.add("user")
def socket_card_dispatch_context(
    request: Request, form: SocketCardDispatchForm,
    user: User = Auth.scope("user"), service: DomainService = DomainService.scope(),
) -> JsonResponse:
    """Resolve a bounded native socket audience through the current shared policy."""
    try:
        claims = AuthSecurity.decode_access_token(request.headers.get(AuthSecurity.API_TOKEN_HEADER, ""))
        if claims.get("internal") != "socket_dispatch" or int(claims["sub"]) != int(user.id):
            return JsonResponse(content={"allowed_recipient_uids": []}, status_code=403)
    except Exception:
        return JsonResponse(content={"allowed_recipient_uids": []}, status_code=403)
    try:
        card_ids = [SnowflakeID.from_short_code(uid) for uid in form.card_uids]
        allowed = []
        for uid in dict.fromkeys(form.recipient_uids):
            recipient_id = SnowflakeID.from_short_code(uid)
            with DbSession.use(readonly=False) as db:
                recipient = db.exec(SqlBuilder.select.table(User).where(User.id == recipient_id)).first()
            if recipient is not None and all(service.card.resolve_readable_card(
                None, card_id, recipient, CollaborationChannel.HumanUI,
            ) is not None for card_id in card_ids):
                allowed.append(uid)
        return JsonResponse(content={"allowed_recipient_uids": allowed})
    except (TypeError, ValueError):
        return JsonResponse(content={"allowed_recipient_uids": []})
