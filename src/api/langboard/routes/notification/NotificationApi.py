from typing import Literal, cast
from fastapi import Depends
from langboard_shared.core.filter import AuthFilter
from langboard_shared.core.routing import ApiErrorCode, ApiException, AppRouter, JsonResponse
from langboard_shared.core.schema import OpenApiSchema
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
    form: NotificationForm = Depends(), user: User = Auth.scope("user"), service: DomainService = DomainService.scope()
) -> JsonResponse:
    if form.time_range not in ["3d", "7d", "1m", "all"]:
        form.time_range = "3d"
    notifications, has_more, unread_count = service.notification.get_api_list(
        user, cast(Literal["3d", "7d", "1m", "all"], form.time_range), form.page, form.limit
    )
    return JsonResponse(content={"notifications": notifications, "has_more": has_more, "unread_count": unread_count})


def _parse_notification_uid(notification_uid: str) -> SnowflakeID:
    try:
        notification_id = SnowflakeID.from_short_code(notification_uid)
    except ValueError as error:
        raise ApiException.BadRequest_400(ApiErrorCode.VA0000) from error

    if notification_id <= 0:
        raise ApiException.BadRequest_400(ApiErrorCode.VA0000)
    return notification_id


@AppRouter.api.put("/notifications/read-all", tags=["Notification"], responses=OpenApiSchema().auth().forbidden().get())
@AuthFilter.add("user")
def read_all_notifications(
    user: User = Auth.scope("user"), service: DomainService = DomainService.scope()
) -> JsonResponse:
    mutation = service.notification.read_all(user)
    return JsonResponse(content=mutation)


@AppRouter.api.put(
    "/notifications/{notification_uid}/read",
    tags=["Notification"],
    responses=OpenApiSchema().auth().forbidden().err(400, ApiErrorCode.VA0000).get(),
)
@AuthFilter.add("user")
def read_notification(
    notification_uid: str, user: User = Auth.scope("user"), service: DomainService = DomainService.scope()
) -> JsonResponse:
    mutation = service.notification.read(user, _parse_notification_uid(notification_uid))
    return JsonResponse(content=mutation)


@AppRouter.api.delete("/notifications", tags=["Notification"], responses=OpenApiSchema().auth().forbidden().get())
@AuthFilter.add("user")
def delete_all_notifications(
    user: User = Auth.scope("user"), service: DomainService = DomainService.scope()
) -> JsonResponse:
    mutation = service.notification.delete_all(user)
    return JsonResponse(content=mutation)


@AppRouter.api.delete(
    "/notifications/{notification_uid}",
    tags=["Notification"],
    responses=OpenApiSchema().auth().forbidden().err(400, ApiErrorCode.VA0000).get(),
)
@AuthFilter.add("user")
def delete_notification(
    notification_uid: str, user: User = Auth.scope("user"), service: DomainService = DomainService.scope()
) -> JsonResponse:
    mutation = service.notification.delete(user, _parse_notification_uid(notification_uid))
    return JsonResponse(content=mutation)
