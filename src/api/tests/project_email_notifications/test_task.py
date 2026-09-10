from contextlib import contextmanager
from types import SimpleNamespace
import pytest
from langboard_shared.core.types import SnowflakeID
from langboard_shared.tasks.notifications import ProjectEmailNotificationQueue, ProjectEmailNotificationTask


def test_activity_email_delivery_owns_service_lifecycle(monkeypatch: pytest.MonkeyPatch) -> None:
    activity = SimpleNamespace()
    calls: list[tuple[object, ...]] = []
    notification_service = SimpleNamespace(
        send_activity_email=lambda *args: calls.append(("send", *args)) or True,
        record_delivery=lambda *args, **kwargs: calls.append(("record", *args, kwargs)),
    )

    @contextmanager
    def use_service():
        calls.append(("open",))
        yield SimpleNamespace(project_email_notification=notification_service)
        calls.append(("close",))

    monkeypatch.setattr(ProjectEmailNotificationTask, "_get_activity", lambda *_: activity)
    monkeypatch.setattr(ProjectEmailNotificationTask.DomainService, "use", use_service)

    delivered = ProjectEmailNotificationTask._deliver_project_activity_email(
        "project_activity",
        SnowflakeID(1),
        "member@example.com",
    )

    assert delivered is True
    assert [call[0] for call in calls] == ["open", "send", "record", "close"]


def test_activity_email_delivery_closes_service_before_retry(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []
    notification_service = SimpleNamespace(send_activity_email=lambda *_: False)

    @contextmanager
    def use_service():
        calls.append("open")
        try:
            yield SimpleNamespace(project_email_notification=notification_service)
        finally:
            calls.append("close")

    monkeypatch.setattr(ProjectEmailNotificationTask, "_get_activity", lambda *_: SimpleNamespace())
    monkeypatch.setattr(ProjectEmailNotificationTask.DomainService, "use", use_service)

    with pytest.raises(ProjectEmailNotificationTask.ProjectEmailDeliveryError):
        ProjectEmailNotificationTask._deliver_project_activity_email(
            "project_activity",
            SnowflakeID(1),
            "member@example.com",
        )

    assert calls == ["open", "close"]


def test_activity_email_queue_uses_registered_task(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[str, SnowflakeID]] = []
    monkeypatch.setattr(ProjectEmailNotificationQueue, "_fanout_task", lambda *args: calls.append(args))

    ProjectEmailNotificationQueue.enqueue_project_activity_email("project_activity", SnowflakeID(1))

    assert calls == [("project_activity", 1)]
