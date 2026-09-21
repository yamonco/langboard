from typing import Literal, cast
from fastapi import Depends
from langboard_shared.core.filter import AuthFilter
from langboard_shared.core.routing import AppRouter, JsonResponse
from langboard_shared.core.schema import OpenApiSchema
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
    )
    return JsonResponse(content={"notifications": notifications, "has_more": has_more, "unread_count": unread_count})
