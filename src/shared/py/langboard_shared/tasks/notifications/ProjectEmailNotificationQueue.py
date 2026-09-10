from collections.abc import Callable
from typing import Any
from ...core.broker import Broker
from ...core.broker.TaskParameters import TaskParameters
from ...core.types import SnowflakeID


PROJECT_EMAIL_FANOUT_TASK = (
    "langboard_shared.tasks.notifications.ProjectEmailNotificationTask.fanout_project_activity_email"
)

_fanout_task: Callable[[str, SnowflakeID], Any] | None = None


def register_project_activity_email_task(task: Callable[[str, SnowflakeID], Any]) -> None:
    global _fanout_task
    _fanout_task = task


def enqueue_project_activity_email(activity_table: str, activity_id: SnowflakeID) -> None:
    if _fanout_task is not None:
        _fanout_task(activity_table, activity_id)
        return

    args, kwargs = TaskParameters(activity_table, activity_id).pack()
    Broker.celery.send_task(PROJECT_EMAIL_FANOUT_TASK, args=args, kwargs=kwargs)
