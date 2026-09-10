from typing import Any
from pydantic import BaseModel
from ...domain.models import User, UserNotification
from ..broadcast import DispatcherModel, DispatcherQueue
from ..resources.locales.EmailTemplateNames import TEmailTemplateName
from ..utils.decorators import staticclass


class NotificationPublishModel(BaseModel):
    notification: UserNotification
    api_notification: dict[str, Any]
    target_user: User
    scope_models: list[tuple[str, int]] | None

    # email
    email_template_name: TEmailTemplateName | None
    email_formats: dict[str, str] | None


@staticclass
class NotificationPublisher:
    @staticmethod
    def put_dispather(model: NotificationPublishModel):
        dispatacher_model = DispatcherModel(event="notification_publish", data=model.model_dump())
        DispatcherQueue.put(dispatacher_model)

        # Reuse the signed webhook transport for external action-required events.
        # Import locally so the core publisher does not create a module cycle at startup.
        from ...tasks.webhooks import WebhookTask
        from ...tasks.webhooks.utils import build_notification_work_event

        work_event = build_notification_work_event(model.notification)
        if work_event is not None:
            WebhookTask.webhook_task(work_event)
