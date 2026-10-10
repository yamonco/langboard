from typing import Literal, cast
from fastapi import Depends, Request
from langboard_shared.core.filter import AuthFilter
from langboard_shared.core.routing import AppRouter, JsonResponse
from langboard_shared.core.schema import OpenApiSchema
from langboard_shared.core.security.CollaborationChannel import CollaborationChannel
from langboard_shared.core.types import SnowflakeID
from langboard_shared.domain.models import User, UserNotification
from langboard_shared.domain.services import DomainService
from langboard_shared.security import Auth
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
