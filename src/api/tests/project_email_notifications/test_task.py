from contextlib import contextmanager
from email.message import EmailMessage
from types import SimpleNamespace
from unittest.mock import Mock
import pytest
from langboard_shared.core.types import SnowflakeID
from langboard_shared.domain.models.NotificationEmailDelivery import NotificationEmailDeliveryStatus
from langboard_shared.tasks.notifications import ProjectEmailNotificationQueue, ProjectEmailNotificationTask


def _delivery_service(monkeypatch: pytest.MonkeyPatch, message: EmailMessage | None, accepted: bool = True):
    activity = SimpleNamespace()
    delivery = SimpleNamespace(
        id=SnowflakeID(7),
        activity_table="project_activity",
        activity_id=SnowflakeID(1),
        recipient_email="member@example.com",
    )
    repository = Mock()
    repository.accept_one.return_value = delivery
    repository.claim_one.return_value = delivery
    repository.begin_sending.return_value = True
    repository.complete.return_value = True
    project_email = Mock()
    project_email.repo.project_activity_email_delivery = repository
    project_email.prepare_activity_email.return_value = message
    smtp = Mock()
    smtp.send_message.return_value = accepted
    service = SimpleNamespace(
        project_email_notification=project_email,
        email=smtp,
    )

    @contextmanager
    def use_service():
        yield service

    monkeypatch.setattr(ProjectEmailNotificationTask, "_get_activity", lambda *_: activity)
    monkeypatch.setattr(ProjectEmailNotificationTask.DomainService, "use", use_service)
    return service, delivery


def test_activity_email_delivery_records_only_confirmed_smtp_acceptance(monkeypatch: pytest.MonkeyPatch) -> None:
    service, delivery = _delivery_service(monkeypatch, EmailMessage())

    assert (
        ProjectEmailNotificationTask._deliver_project_activity_email(
            "project_activity", SnowflakeID(1), "MEMBER@example.com"
        )
        is True
    )
    service.project_email_notification.repo.project_activity_email_delivery.complete.assert_called_once_with(
        delivery, NotificationEmailDeliveryStatus.Sent, None
    )
    service.email.send_message.assert_called_once()
    service.project_email_notification.record_delivery.assert_called_once()


def test_activity_email_uncertain_outcome_is_not_retried(monkeypatch: pytest.MonkeyPatch) -> None:
    service, delivery = _delivery_service(monkeypatch, EmailMessage(), accepted=False)

    assert (
        ProjectEmailNotificationTask._deliver_project_activity_email(
            "project_activity", SnowflakeID(1), "member@example.com"
        )
        is False
    )
    service.project_email_notification.repo.project_activity_email_delivery.complete.assert_called_once_with(
        delivery, NotificationEmailDeliveryStatus.Uncertain, "SMTP acceptance could not be confirmed"
    )
    service.project_email_notification.record_delivery.assert_not_called()


def test_suppressed_activity_email_does_not_contact_smtp(monkeypatch: pytest.MonkeyPatch) -> None:
    service, delivery = _delivery_service(monkeypatch, None)

    assert (
        ProjectEmailNotificationTask._deliver_project_activity_email(
            "project_activity", SnowflakeID(1), "member@example.com"
        )
        is False
    )
    service.project_email_notification.repo.project_activity_email_delivery.complete.assert_called_once_with(
        delivery, NotificationEmailDeliveryStatus.Suppressed, "Recipient is no longer eligible"
    )
    service.project_email_notification.repo.project_activity_email_delivery.begin_sending.assert_not_called()
    service.email.send_message.assert_not_called()


def test_duplicate_activity_email_task_does_not_send(monkeypatch: pytest.MonkeyPatch) -> None:
    service, _ = _delivery_service(monkeypatch, EmailMessage())
    service.project_email_notification.repo.project_activity_email_delivery.claim_one.return_value = None

    assert (
        ProjectEmailNotificationTask._deliver_project_activity_email(
            "project_activity", SnowflakeID(1), "member@example.com"
        )
        is False
    )
    service.email.send_message.assert_not_called()


def test_activity_email_queue_uses_registered_task(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[str, SnowflakeID]] = []
    monkeypatch.setattr(ProjectEmailNotificationQueue, "_fanout_task", lambda *args: calls.append(args))

    ProjectEmailNotificationQueue.enqueue_project_activity_email("project_activity", SnowflakeID(1))

    assert calls == [("project_activity", 1)]


def test_recovery_accepts_activity_when_initial_fanout_task_was_lost(monkeypatch: pytest.MonkeyPatch) -> None:
    activity = SimpleNamespace(__tablename__="project_activity", id=SnowflakeID(1))
    recipient = SimpleNamespace(email="member@example.test")
    repository = Mock()
    repository.get_pending_fanout.return_value = [activity]
    repository.accept_recipients.return_value = []
    project_email = Mock()
    project_email.repo.project_activity_email_delivery = repository
    project_email.get_delivery_recipients.return_value = [recipient]
    service = SimpleNamespace(project_email_notification=project_email)

    @contextmanager
    def use_service():
        yield service

    monkeypatch.setattr(ProjectEmailNotificationTask.DomainService, "use", use_service)
    monkeypatch.setattr(ProjectEmailNotificationTask, "Env", SimpleNamespace(MAIL_SERVER="", MAIL_FROM=""))

    assert ProjectEmailNotificationTask.recover_pending_project_activity_email() == 0
    repository.accept_recipients.assert_called_once_with(activity, [recipient.email])
    repository.claim_pending.assert_not_called()


def test_recovery_defers_failed_fanout_and_continues(monkeypatch: pytest.MonkeyPatch) -> None:
    failed = SimpleNamespace(__tablename__="project_activity", id=SnowflakeID(1))
    later = SimpleNamespace(__tablename__="project_activity", id=SnowflakeID(2))
    repository = Mock()
    repository.get_pending_fanout.return_value = [failed, later]
    project_email = Mock()
    project_email.repo.project_activity_email_delivery = repository
    project_email.get_delivery_recipients.side_effect = [RuntimeError("read failed"), []]
    service = SimpleNamespace(project_email_notification=project_email)

    @contextmanager
    def use_service():
        yield service

    monkeypatch.setattr(ProjectEmailNotificationTask.DomainService, "use", use_service)
    monkeypatch.setattr(ProjectEmailNotificationTask, "Env", SimpleNamespace(MAIL_SERVER="", MAIL_FROM=""))

    assert ProjectEmailNotificationTask.recover_pending_project_activity_email() == 0
    repository.defer_pending_fanout.assert_called_once_with(failed)
    repository.accept_recipients.assert_called_once_with(later, [])
