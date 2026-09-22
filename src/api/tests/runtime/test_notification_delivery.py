from contextlib import contextmanager
from datetime import timedelta
from importlib import import_module
from unittest.mock import Mock, call
import pytest
from langboard import ServerRunner
from langboard_shared import FastAPIRunner
from langboard_shared.ai import BotScheduleHelper
from langboard_shared.core.db import DbSession
from langboard_shared.core.db.DbEngine import DbEngine
from langboard_shared.core.publisher import NotificationPublisher
from langboard_shared.core.resources.locales.EmailTemplateNames import TEmailTemplateName
from langboard_shared.core.routing import SocketTopic
from langboard_shared.core.types import SafeDateTime, SnowflakeID
from langboard_shared.domain.models import NotificationEmailDelivery, User, UserNotification
from langboard_shared.domain.models.NotificationEmailDelivery import NotificationEmailDeliveryStatus
from langboard_shared.domain.models.UserNotification import NotificationType
from langboard_shared.domain.models.UserNotificationUnsubscription import NotificationChannel, NotificationScope
from langboard_shared.domain.services import DomainService
from langboard_shared.domain.services.factory.EmailService import EmailService
from langboard_shared.domain.services.factory.NotificationService import NotificationService
from langboard_shared.domain.services.factory.UserNotificationSettingService import UserNotificationSettingService
from langboard_shared.Env import Env
from langboard_shared.helpers import InfraHelper
from langboard_shared.infrastructure.repositories.factory.NotificationEmailDeliveryRepository import (
    NotificationEmailDeliveryRepository,
)
from langboard_shared.infrastructure.repositories.factory.UserNotificationRepository import UserNotificationRepository
from langboard_shared.infrastructure.repositories.factory.UserNotificationSettingRepository import (
    UserNotificationSettingRepository,
)
from langboard_shared.publishers.UserPublisher import UserPublisher
from langboard_shared.tasks.notifications.NotificationWebFanoutTask import recover_pending_web_fanout
from pytest import MonkeyPatch
from sqlalchemy import create_engine, select


def _user(user_id: int) -> User:
    return User.model_construct(id=SnowflakeID(user_id), email=f"user-{user_id}@example.test", preferred_lang="en-US")


@pytest.mark.parametrize("unsubscribed", [False, True])
@pytest.mark.parametrize("email_template", [None, "assigned_to_card"])
def test_new_notification_has_one_python_web_owner(
    monkeypatch: MonkeyPatch, unsubscribed: bool, email_template: TEmailTemplateName | None
) -> None:
    notifier = _user(1)
    target = _user(2)
    events: list[str] = []
    repository = Mock()
    settings = Mock()
    settings.has_unsubscription.side_effect = lambda user, kind, scopes, channel: (
        unsubscribed if channel == NotificationChannel.Web else False
    )
    service = NotificationService(lambda service_type: settings, lambda name: None, repository)
    monkeypatch.setattr(type(Env), "NOTIFICATION_EMAIL_OUTBOX_ENABLED", property(lambda self: True))

    monkeypatch.setattr(InfraHelper, "get_by_id_like", lambda model, identifier: target)

    def insert(notification) -> None:
        events.append("persist")
        assert notification.is_new()
        notification.id = SnowflakeID(3)

    def api_response(notification, references, sender):
        events.append("response")
        assert not notification.is_new()
        return {"uid": notification.get_uid(), "notifier_user": {"uid": notifier.get_uid()}}

    def notified(user, notification) -> None:
        events.append("fanout")
        assert user is target
        assert notification["uid"] == SnowflakeID(3).to_short_code()

    def accept(delivery, web_notification) -> None:
        events.append("email-accepted")
        if web_notification is not None:
            insert(web_notification)
            delivery.notification_id = web_notification.id
        assert delivery.notification_id != SnowflakeID(0)
        assert delivery.recipient_email == target.email

    repository.user_notification.insert.side_effect = insert
    repository.notification_email_delivery.accept.side_effect = accept
    monkeypatch.setattr(service, "convert_to_api_response", api_response)
    monkeypatch.setattr(UserPublisher, "notified", notified)
    legacy_publish = Mock()
    monkeypatch.setattr(NotificationPublisher, "put_dispather", legacy_publish)

    assert service._NotificationService__notify(
        notifier,
        target,
        NotificationType.ProjectInvited,
        None,
        [],
        email_template_name=email_template,
    )

    settings.has_unsubscription.assert_any_call(target, NotificationType.ProjectInvited, None, NotificationChannel.Web)
    if email_template:
        settings.has_unsubscription.assert_any_call(
            target, NotificationType.ProjectInvited, None, NotificationChannel.Email
        )
    assert settings.has_unsubscription.call_count == (2 if email_template else 1)
    expected = (["email-accepted"] if email_template else []) + (["persist"] if not unsubscribed else []) + ["response"]
    if not unsubscribed:
        expected.append("fanout")
    assert events == expected
    assert repository.user_notification.complete_web_fanout.call_count == (0 if unsubscribed else 1)
    assert repository.notification_email_delivery.accept.call_count == int(email_template is not None)
    legacy_publish.assert_not_called()


def test_failed_web_publish_remains_pending_and_does_not_block_email(monkeypatch: MonkeyPatch) -> None:
    notifier = _user(1)
    target = _user(2)
    repository = Mock()

    def accept(delivery, web_notification):
        assert web_notification is not None
        web_notification.id = SnowflakeID(3)
        delivery.notification_id = web_notification.id

    repository.notification_email_delivery.accept.side_effect = accept
    settings = Mock()
    settings.has_unsubscription.return_value = False
    service = NotificationService(lambda service_type: settings, lambda name: None, repository)
    monkeypatch.setattr(type(Env), "NOTIFICATION_EMAIL_OUTBOX_ENABLED", property(lambda self: True))
    monkeypatch.setattr(InfraHelper, "get_by_id_like", lambda model, identifier: target)
    monkeypatch.setattr(
        service,
        "convert_to_api_response",
        lambda notification, references, sender: {"uid": notification.get_uid()},
    )
    monkeypatch.setattr(UserPublisher, "notified", Mock(side_effect=RuntimeError("broker unavailable")))
    legacy_publish = Mock()
    monkeypatch.setattr(NotificationPublisher, "put_dispather", legacy_publish)

    assert service._NotificationService__notify(
        notifier,
        target,
        NotificationType.ProjectInvited,
        None,
        [],
        email_template_name="assigned_to_card",
    )

    delivery, persisted = repository.notification_email_delivery.accept.call_args.args
    assert delivery.notification_id == persisted.id
    assert persisted.web_fanout_pending is True
    repository.user_notification.complete_web_fanout.assert_not_called()
    legacy_publish.assert_not_called()


def test_email_outbox_defaults_to_legacy_node_owner(monkeypatch: MonkeyPatch) -> None:
    notifier = _user(1)
    target = _user(2)
    repository = Mock()
    repository.user_notification.insert.side_effect = lambda notification: setattr(notification, "id", SnowflakeID(3))
    settings = Mock()
    settings.has_unsubscription.return_value = False
    service = NotificationService(lambda service_type: settings, lambda name: None, repository)
    monkeypatch.setattr(type(Env), "NOTIFICATION_EMAIL_OUTBOX_ENABLED", property(lambda self: False))
    monkeypatch.setattr(InfraHelper, "get_by_id_like", lambda model, identifier: target)
    monkeypatch.setattr(
        service, "convert_to_api_response", lambda notification, references, sender: {"uid": notification.get_uid()}
    )
    monkeypatch.setattr(UserPublisher, "notified", Mock())
    legacy_publish = Mock()
    monkeypatch.setattr(NotificationPublisher, "put_dispather", legacy_publish)

    assert service._NotificationService__notify(
        notifier, target, NotificationType.ProjectInvited, None, [], email_template_name="assigned_to_card"
    )

    repository.notification_email_delivery.accept.assert_not_called()
    legacy_model = legacy_publish.call_args.args[0]
    assert legacy_model.web_handled_by_python is True
    assert legacy_model.email_template_name == "assigned_to_card"


def test_recovery_command_attempts_email_after_web_failure(monkeypatch: MonkeyPatch) -> None:
    module = import_module("langboard.commands.RunNotificationWebFanoutCommand")
    assert not module.RunNotificationWebFanoutCommand.is_only_in_dev()
    monkeypatch.setattr(module, "recover_pending_web_fanout", Mock(side_effect=RuntimeError("web unavailable")))
    recover_email = Mock()
    purge_email = Mock()
    monkeypatch.setattr(module, "recover_pending_email_delivery", recover_email)
    monkeypatch.setattr(module, "purge_terminal_email_deliveries", purge_email)

    with pytest.raises(RuntimeError, match="web unavailable"):
        module.RunNotificationWebFanoutCommand().execute(module.RunNotificationWebFanoutCommandOptions())

    recover_email.assert_called_once_with()
    purge_email.assert_called_once_with()


def test_recovery_publishes_and_marks_pending_web_notification(monkeypatch: MonkeyPatch) -> None:
    recipient = _user(2)
    notification = UserNotification.model_construct(
        id=SnowflakeID(3), receiver_id=recipient.id, web_fanout_pending=True
    )
    repository = Mock()
    repository.user_notification.get_pending_web_fanout.return_value = [notification]
    service = NotificationService(lambda service_type: None, lambda name: None, repository)
    monkeypatch.setattr(InfraHelper, "get_by_id_like", lambda model, identifier: recipient)
    monkeypatch.setattr(service, "convert_to_api_response", lambda notification: {"uid": notification.get_uid()})
    publish = Mock()
    monkeypatch.setattr(UserPublisher, "notified", publish)

    assert service.recover_pending_web_fanout() == 1

    publish.assert_called_once_with(recipient, {"uid": notification.get_uid()})
    repository.user_notification.complete_web_fanout.assert_called_once_with(notification)
    assert repository.user_notification.get_pending_web_fanout.call_args.args[1] == 50


@pytest.mark.parametrize("failure", ["missing_recipient", "invalid_payload", "broker_failure"])
def test_recovery_defers_failed_web_notification(monkeypatch: MonkeyPatch, failure: str) -> None:
    recipient = _user(2)
    notification = UserNotification.model_construct(
        id=SnowflakeID(3), receiver_id=recipient.id, web_fanout_pending=True
    )
    repository = Mock()
    repository.user_notification.get_pending_web_fanout.return_value = [notification]
    service = NotificationService(lambda service_type: None, lambda name: None, repository)
    monkeypatch.setattr(
        InfraHelper,
        "get_by_id_like",
        lambda model, identifier: None if failure == "missing_recipient" else recipient,
    )
    if failure == "invalid_payload":
        monkeypatch.setattr(service, "convert_to_api_response", Mock(side_effect=ValueError("invalid payload")))
    else:
        monkeypatch.setattr(service, "convert_to_api_response", lambda notification: {"uid": notification.get_uid()})
    if failure == "broker_failure":
        monkeypatch.setattr(UserPublisher, "notified", Mock(side_effect=RuntimeError("broker unavailable")))

    assert service.recover_pending_web_fanout() == 0

    repository.user_notification.defer_web_fanout.assert_called_once_with(notification)
    repository.user_notification.complete_web_fanout.assert_not_called()


@pytest.mark.parametrize("lock_acquired", [False, True])
def test_web_fanout_recovery_has_one_database_owner(monkeypatch: MonkeyPatch, lock_acquired: bool) -> None:
    database = Mock()
    database.exec.return_value.first.return_value = lock_acquired
    service = Mock()
    service.notification.recover_pending_web_fanout.return_value = 2

    @contextmanager
    def use_db(readonly: bool):
        assert not readonly
        yield database

    @contextmanager
    def use_service():
        yield service

    monkeypatch.setattr(DbSession, "use", use_db)
    monkeypatch.setattr(DomainService, "use", use_service)

    assert recover_pending_web_fanout() == (2 if lock_acquired else 0)
    assert service.notification.recover_pending_web_fanout.call_count == int(lock_acquired)


def test_server_registers_recovery_crons(monkeypatch: MonkeyPatch) -> None:
    cron = Mock()
    cron.find_comment.return_value = []
    cron_utils = Mock()
    cron_utils.get_cron.return_value = cron
    cron_utils.create_job.return_value = True
    monkeypatch.setattr(BotScheduleHelper, "utils", cron_utils)
    monkeypatch.setattr(FastAPIRunner, "run", Mock())

    ServerRunner.run()

    assert cron_utils.create_job.call_args_list == [
        call(cron, "* * * * *", "/app/scripts/run_notification_recovery.sh", "notification-web-fanout-recovery"),
        call(cron, "* * * * *", "/app/scripts/run_ollama_pull_recovery.sh", "ollama-pull-recovery"),
        call(cron, "* * * * *", "/app/scripts/run_internal_bot_run_recovery.sh", "internal-bot-run-recovery"),
    ]
    assert cron_utils.save_cron.call_args_list == [call(cron), call(cron), call(cron)]
    cron_utils.reload_cron.assert_called_once_with()


def test_server_replaces_stale_recovery_crons(monkeypatch: MonkeyPatch) -> None:
    cron = Mock()
    old_job = Mock(command="/bin/bash /app/scripts/run_notification_recovery.sh", slices="* * * * *")
    cron.find_comment.return_value = [old_job]
    cron_utils = Mock()
    cron_utils.get_cron.return_value = cron
    monkeypatch.setattr(BotScheduleHelper, "utils", cron_utils)
    monkeypatch.setattr(FastAPIRunner, "run", Mock())

    ServerRunner.run()

    assert cron_utils.remove_job.call_args_list == [
        call(cron, "notification-web-fanout-recovery"),
        call(cron, "ollama-pull-recovery"),
        call(cron, "internal-bot-run-recovery"),
    ]
    assert cron_utils.create_job.call_args_list == [
        call(cron, "* * * * *", "/app/scripts/run_notification_recovery.sh", "notification-web-fanout-recovery"),
        call(cron, "* * * * *", "/app/scripts/run_ollama_pull_recovery.sh", "ollama-pull-recovery"),
        call(cron, "* * * * *", "/app/scripts/run_internal_bot_run_recovery.sh", "internal-bot-run-recovery"),
    ]
    assert cron_utils.save_cron.call_args_list == [call(cron), call(cron), call(cron)]
    cron_utils.reload_cron.assert_called_once_with()


def test_user_notification_publisher_uses_private_fanout(monkeypatch: MonkeyPatch) -> None:
    published = []
    monkeypatch.setattr(
        UserPublisher, "put_dispather", lambda data, publish_model: published.append((data, publish_model))
    )
    target = _user(2)
    notification = {"uid": SnowflakeID(3).to_short_code()}

    UserPublisher.notified(target, notification)

    assert len(published) == 1
    data, publish_model = published[0]
    assert data == {"notification": notification}
    assert publish_model.topic == SocketTopic.UserPrivate
    assert publish_model.topic_id == target.get_uid()
    assert publish_model.event == "user:notified"
    assert publish_model.data_keys == ["notification"]


def test_user_notification_mutation_publisher_uses_private_fanout(monkeypatch: MonkeyPatch) -> None:
    published = []
    monkeypatch.setattr(
        UserPublisher, "put_dispather", lambda data, publish_model: published.append((data, publish_model))
    )
    target = _user(2)
    mutation = {"action": "delete_all", "unread_count": 0}

    UserPublisher.notification_mutated(target, mutation)

    assert len(published) == 1
    data, publish_model = published[0]
    assert data == mutation
    assert publish_model.topic == SocketTopic.UserPrivate
    assert publish_model.topic_id == target.get_uid()
    assert publish_model.event == "user:notification:mutated"
    assert publish_model.data_keys == ["action", "unread_count"]


def test_python_notification_insert_persists_a_new_row(monkeypatch: MonkeyPatch) -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    User.__table__.create(engine)
    UserNotification.__table__.create(engine)
    monkeypatch.setattr(DbEngine, "get_main_engine", lambda: engine)
    repository = UserNotificationRepository(lambda repository_type: None, lambda name: None)
    notification = UserNotification(
        notifier_type="user",
        notifier_id=SnowflakeID(1),
        receiver_id=SnowflakeID(2),
        notification_type=NotificationType.ProjectInvited,
        record_list=[],
        web_fanout_pending=True,
    )

    assert notification.is_new()
    repository.insert(notification)

    assert not notification.is_new()
    with engine.connect() as connection:
        row = connection.execute(
            select(UserNotification.__table__).where(UserNotification.__table__.c.id == notification.id)
        ).one()
    assert row.receiver_id == SnowflakeID(2)
    assert row.record_list == []
    pending = repository.get_pending_web_fanout(SafeDateTime.now() + timedelta(days=1), 10)
    assert [item.id for item in pending] == [notification.id]
    repository.complete_web_fanout(notification)
    assert repository.get_pending_web_fanout(SafeDateTime.now() + timedelta(days=1), 10) == []
    engine.dispose()


def test_email_acceptance_is_atomic_with_web_notification(monkeypatch: MonkeyPatch) -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    User.__table__.create(engine)
    UserNotification.__table__.create(engine)
    NotificationEmailDelivery.__table__.create(engine)
    monkeypatch.setattr(DbEngine, "get_main_engine", lambda: engine)
    repository = NotificationEmailDeliveryRepository(lambda repository_type: None, lambda name: None)
    notification = UserNotification(
        notifier_type="user",
        notifier_id=SnowflakeID(1),
        receiver_id=SnowflakeID(2),
        notification_type=NotificationType.ProjectInvited,
        web_fanout_pending=True,
    )
    delivery = NotificationEmailDelivery(
        notification_id=SnowflakeID(0),
        receiver_id=SnowflakeID(2),
        notification_type=NotificationType.ProjectInvited,
        recipient_email="recipient@example.test",
        preferred_lang="en-US",
        template_name="assigned_to_card",
    )

    repository.accept(delivery, notification)

    assert notification.id != SnowflakeID(0)
    assert delivery.notification_id == notification.id
    with engine.connect() as connection:
        assert connection.execute(select(UserNotification.__table__)).one().id == notification.id
        assert connection.execute(select(NotificationEmailDelivery.__table__)).one().notification_id == notification.id

    claimed = repository.claim_pending(1)
    assert [item.id for item in claimed] == [delivery.id]
    assert repository.claim_pending(1) == []
    assert repository.begin_sending(claimed[0])
    repository.complete_sending(claimed[0], NotificationEmailDeliveryStatus.Sent)
    with engine.connect() as connection:
        persisted = connection.execute(select(NotificationEmailDelivery.__table__)).one()
    assert persisted.status == NotificationEmailDeliveryStatus.Sent
    assert persisted.sent_at is not None
    engine.dispose()


def test_email_acceptance_rolls_back_web_row_on_delivery_insert_failure(monkeypatch: MonkeyPatch) -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    User.__table__.create(engine)
    UserNotification.__table__.create(engine)
    NotificationEmailDelivery.__table__.create(engine)
    monkeypatch.setattr(DbEngine, "get_main_engine", lambda: engine)
    repository = NotificationEmailDeliveryRepository(lambda repository_type: None, lambda name: None)
    notification = UserNotification(
        notifier_type="user",
        notifier_id=SnowflakeID(1),
        receiver_id=SnowflakeID(2),
        notification_type=NotificationType.ProjectInvited,
    )
    delivery = NotificationEmailDelivery(
        notification_id=SnowflakeID(0),
        receiver_id=SnowflakeID(2),
        notification_type=NotificationType.ProjectInvited,
        recipient_email="recipient@example.test",
        preferred_lang="en-US",
        template_name="assigned_to_card",
    )
    original_insert = DbSession.insert

    def insert(db: DbSession, model: UserNotification | NotificationEmailDelivery) -> None:
        if isinstance(model, NotificationEmailDelivery):
            raise RuntimeError("delivery insert failed")
        original_insert(db, model)

    monkeypatch.setattr(DbSession, "insert", insert)
    with pytest.raises(RuntimeError, match="delivery insert failed"):
        repository.accept(delivery, notification)

    with engine.connect() as connection:
        assert connection.execute(select(UserNotification.__table__)).all() == []
        assert connection.execute(select(NotificationEmailDelivery.__table__)).all() == []
    engine.dispose()


def test_stale_sending_email_is_not_retried_automatically(monkeypatch: MonkeyPatch) -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    User.__table__.create(engine)
    NotificationEmailDelivery.__table__.create(engine)
    monkeypatch.setattr(DbEngine, "get_main_engine", lambda: engine)
    repository = NotificationEmailDeliveryRepository(lambda repository_type: None, lambda name: None)
    delivery = NotificationEmailDelivery(
        notification_id=SnowflakeID(3),
        receiver_id=SnowflakeID(2),
        notification_type=NotificationType.ProjectInvited,
        recipient_email="recipient@example.test",
        preferred_lang="en-US",
        template_name="assigned_to_card",
        status=NotificationEmailDeliveryStatus.Sending,
        claimed_at=SafeDateTime.now() - timedelta(minutes=11),
    )
    repository.insert(delivery)

    assert repository.mark_stale_uncertain(SafeDateTime.now() - timedelta(minutes=10), 8) == 1
    assert repository.claim_pending(8) == []
    with engine.connect() as connection:
        persisted = connection.execute(select(NotificationEmailDelivery.__table__)).one()
    assert persisted.status == NotificationEmailDeliveryStatus.Uncertain
    assert persisted.failure_reason is not None
    engine.dispose()


def test_stale_preparing_email_is_requeued_and_old_worker_is_fenced(monkeypatch: MonkeyPatch) -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    User.__table__.create(engine)
    NotificationEmailDelivery.__table__.create(engine)
    monkeypatch.setattr(DbEngine, "get_main_engine", lambda: engine)
    repository = NotificationEmailDeliveryRepository(lambda repository_type: None, lambda name: None)
    delivery = NotificationEmailDelivery(
        notification_id=SnowflakeID(3),
        receiver_id=SnowflakeID(2),
        notification_type=NotificationType.ProjectInvited,
        recipient_email="recipient@example.test",
        preferred_lang="en-US",
        template_name="assigned_to_card",
        status=NotificationEmailDeliveryStatus.Preparing,
        claimed_at=SafeDateTime.now() - timedelta(minutes=11),
    )
    repository.insert(delivery)

    assert repository.mark_stale_preparing_pending(SafeDateTime.now() - timedelta(minutes=10), 8) == 1
    assert not repository.begin_sending(delivery)
    reclaimed = repository.claim_pending(8)
    assert [item.id for item in reclaimed] == [delivery.id]
    assert not repository.begin_sending(delivery)
    assert repository.begin_sending(reclaimed[0])
    repository.complete_sending(reclaimed[0], NotificationEmailDeliveryStatus.Sent)
    with engine.connect() as connection:
        persisted = connection.execute(select(NotificationEmailDelivery.__table__)).one()
    assert persisted.status == NotificationEmailDeliveryStatus.Sent
    engine.dispose()


def test_stale_sending_worker_cannot_complete_retried_delivery(monkeypatch: MonkeyPatch) -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    User.__table__.create(engine)
    NotificationEmailDelivery.__table__.create(engine)
    monkeypatch.setattr(DbEngine, "get_main_engine", lambda: engine)
    repository = NotificationEmailDeliveryRepository(lambda repository_type: None, lambda name: None)
    delivery = NotificationEmailDelivery(
        notification_id=SnowflakeID(3),
        receiver_id=SnowflakeID(2),
        notification_type=NotificationType.ProjectInvited,
        recipient_email="recipient@example.test",
        preferred_lang="en-US",
        template_name="assigned_to_card",
    )
    repository.insert(delivery)

    first_worker = repository.claim_pending(1)[0]
    assert repository.begin_sending(first_worker)
    assert repository.mark_stale_uncertain(SafeDateTime.now() + timedelta(seconds=1), 1) == 1
    assert repository.resolve_review_item(
        delivery.id,
        NotificationEmailDeliveryStatus.Uncertain,
        NotificationEmailDeliveryStatus.Pending,
        "Operator retry under ticket OPS-123",
    )
    second_worker = repository.claim_pending(1)[0]
    assert repository.begin_sending(second_worker)

    repository.complete_sending(first_worker, NotificationEmailDeliveryStatus.Sent)
    with engine.connect() as connection:
        persisted = connection.execute(select(NotificationEmailDelivery.__table__)).one()
    assert persisted.status == NotificationEmailDeliveryStatus.Sending
    assert second_worker.claimed_at is not None
    assert persisted.claimed_at == second_worker.claimed_at.replace(tzinfo=None)

    repository.complete_sending(second_worker, NotificationEmailDeliveryStatus.Sent)
    with engine.connect() as connection:
        persisted = connection.execute(select(NotificationEmailDelivery.__table__)).one()
    assert persisted.status == NotificationEmailDeliveryStatus.Sent
    engine.dispose()


def test_email_review_resolution_requires_current_state_and_records_decision(monkeypatch: MonkeyPatch) -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    User.__table__.create(engine)
    NotificationEmailDelivery.__table__.create(engine)
    monkeypatch.setattr(DbEngine, "get_main_engine", lambda: engine)
    monkeypatch.setattr(DbEngine, "get_readonly_engine", lambda: engine)
    repository = NotificationEmailDeliveryRepository(lambda repository_type: None, lambda name: None)
    delivery = NotificationEmailDelivery(
        notification_id=SnowflakeID(3),
        receiver_id=SnowflakeID(2),
        notification_type=NotificationType.ProjectInvited,
        recipient_email="recipient@example.test",
        preferred_lang="en-US",
        template_name="assigned_to_card",
        status=NotificationEmailDeliveryStatus.Uncertain,
        failure_reason="SMTP acceptance could not be confirmed",
    )
    repository.insert(delivery)
    service = NotificationService(
        lambda service_type: None, lambda name: None, Mock(notification_email_delivery=repository)
    )

    assert [item.id for item in service.get_email_deliveries_for_review()] == [delivery.id]
    with pytest.raises(ValueError, match="acknowledgement"):
        service.resolve_email_delivery_review(delivery.id, "retry", "OPS-123")
    with pytest.raises(ValueError, match="ticket"):
        service.resolve_email_delivery_review(delivery.id, "retry", "", acknowledge_uncertain=True)
    assert service.resolve_email_delivery_review(delivery.id, "retry", "OPS-123", acknowledge_uncertain=True)
    assert not repository.resolve_review_item(
        delivery.id,
        NotificationEmailDeliveryStatus.Uncertain,
        NotificationEmailDeliveryStatus.Closed,
        "stale operator",
    )
    with engine.connect() as connection:
        persisted = connection.execute(select(NotificationEmailDelivery.__table__)).one()
    assert persisted.status == NotificationEmailDeliveryStatus.Pending
    assert persisted.failure_reason == "SMTP acceptance could not be confirmed"
    assert persisted.review_note.startswith("Operator retry under ticket OPS-123")
    assert repository.claim_pending(1)[0].id == delivery.id
    engine.dispose()


@pytest.mark.parametrize("action", ["confirm-sent", "close"])
def test_email_review_closes_uncertain_without_requeue(monkeypatch: MonkeyPatch, action: str) -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    User.__table__.create(engine)
    NotificationEmailDelivery.__table__.create(engine)
    monkeypatch.setattr(DbEngine, "get_main_engine", lambda: engine)
    monkeypatch.setattr(DbEngine, "get_readonly_engine", lambda: engine)
    repository = NotificationEmailDeliveryRepository(lambda repository_type: None, lambda name: None)
    delivery = NotificationEmailDelivery(
        notification_id=SnowflakeID(3),
        receiver_id=SnowflakeID(2),
        notification_type=NotificationType.ProjectInvited,
        recipient_email="recipient@example.test",
        preferred_lang="en-US",
        template_name="assigned_to_card",
        status=NotificationEmailDeliveryStatus.Uncertain,
    )
    repository.insert(delivery)
    service = NotificationService(
        lambda service_type: None, lambda name: None, Mock(notification_email_delivery=repository)
    )

    assert service.resolve_email_delivery_review(delivery.id, action, "OPS-456", acknowledge_uncertain=True)

    assert service.get_email_deliveries_for_review() == []
    assert repository.claim_pending(1) == []
    with engine.connect() as connection:
        persisted = connection.execute(select(NotificationEmailDelivery.__table__)).one()
    assert persisted.status == (
        NotificationEmailDeliveryStatus.ConfirmedSent
        if action == "confirm-sent"
        else NotificationEmailDeliveryStatus.Closed
    )
    assert persisted.sent_at is None
    assert persisted.review_note is not None and "OPS-456" in persisted.review_note
    engine.dispose()


def test_email_review_rejects_confirming_failed_delivery(monkeypatch: MonkeyPatch) -> None:
    repository = Mock()
    repository.notification_email_delivery.get_review_item.return_value = NotificationEmailDelivery.model_construct(
        id=SnowflakeID(4), status=NotificationEmailDeliveryStatus.Failed
    )
    service = NotificationService(lambda service_type: None, lambda name: None, repository)

    with pytest.raises(ValueError, match="Only an uncertain"):
        service.resolve_email_delivery_review(SnowflakeID(4), "confirm-sent", "OPS-789")
    with pytest.raises(ValueError, match="Invalid email review action"):
        service.resolve_email_delivery_review(SnowflakeID(4), "invalid", "OPS-789")
    repository.notification_email_delivery.resolve_review_item.assert_not_called()


def test_email_retention_deletes_only_old_terminal_rows_in_bounded_batches(monkeypatch: MonkeyPatch) -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    User.__table__.create(engine)
    NotificationEmailDelivery.__table__.create(engine)
    monkeypatch.setattr(DbEngine, "get_main_engine", lambda: engine)
    repository = NotificationEmailDeliveryRepository(lambda repository_type: None, lambda name: None)
    old_time = SafeDateTime.now() - timedelta(days=100)
    recent_time = SafeDateTime.now() - timedelta(days=1)
    terminal = [
        NotificationEmailDeliveryStatus.Sent,
        NotificationEmailDeliveryStatus.Suppressed,
        NotificationEmailDeliveryStatus.ConfirmedSent,
        NotificationEmailDeliveryStatus.Closed,
    ]
    active = [
        NotificationEmailDeliveryStatus.Pending,
        NotificationEmailDeliveryStatus.Preparing,
        NotificationEmailDeliveryStatus.Sending,
        NotificationEmailDeliveryStatus.Failed,
        NotificationEmailDeliveryStatus.Uncertain,
    ]
    deliveries = [
        NotificationEmailDelivery(
            notification_id=SnowflakeID(),
            receiver_id=SnowflakeID(2),
            notification_type=NotificationType.ProjectInvited,
            recipient_email="recipient@example.test",
            preferred_lang="en-US",
            template_name="assigned_to_card",
            status=status,
            created_at=old_time,
        )
        for status in terminal + active
    ]
    deliveries.append(
        NotificationEmailDelivery(
            notification_id=SnowflakeID(),
            receiver_id=SnowflakeID(2),
            notification_type=NotificationType.ProjectInvited,
            recipient_email="recipient@example.test",
            preferred_lang="en-US",
            template_name="assigned_to_card",
            status=NotificationEmailDeliveryStatus.Sent,
            created_at=recent_time,
        )
    )
    repository.insert(deliveries)
    service = NotificationService(
        lambda service_type: None, lambda name: None, Mock(notification_email_delivery=repository)
    )

    assert service.purge_terminal_email_deliveries(limit=2) == 2
    assert service.purge_terminal_email_deliveries(limit=2) == 2
    assert service.purge_terminal_email_deliveries(limit=2) == 0

    with engine.connect() as connection:
        remaining = connection.execute(select(NotificationEmailDelivery.__table__)).all()
    assert {row.id for row in remaining} == {delivery.id for delivery in deliveries[4:]}
    engine.dispose()


def test_email_retention_rejects_invalid_policy(monkeypatch: MonkeyPatch) -> None:
    repository = Mock()
    service = NotificationService(lambda service_type: None, lambda name: None, repository)
    monkeypatch.setattr(type(Env), "NOTIFICATION_EMAIL_OUTBOX_RETENTION_DAYS", property(lambda self: 0))

    with pytest.raises(ValueError, match="retention"):
        service.purge_terminal_email_deliveries()
    repository.notification_email_delivery.purge_terminal_before.assert_not_called()


@pytest.mark.parametrize(
    ("smtp_accepted", "expected_status"),
    [
        (True, NotificationEmailDeliveryStatus.Sent),
        (False, NotificationEmailDeliveryStatus.Uncertain),
    ],
)
def test_email_recovery_records_smtp_outcome(
    monkeypatch: MonkeyPatch, smtp_accepted: bool, expected_status: NotificationEmailDeliveryStatus
) -> None:
    recipient = _user(2)
    delivery = NotificationEmailDelivery.model_construct(
        id=SnowflakeID(4),
        receiver_id=recipient.id,
        notification_type=NotificationType.ProjectInvited,
        scope_models=None,
        recipient_email=recipient.email,
        preferred_lang="en-US",
        template_name="assigned_to_card",
        formats={},
    )
    repository = Mock()
    repository.notification_email_delivery.claim_pending.return_value = [delivery]
    settings = Mock()
    settings.has_unsubscription.return_value = False
    email_service = Mock()
    email_service.send_message.return_value = smtp_accepted
    services = {UserNotificationSettingService: settings, EmailService: email_service}
    service = NotificationService(lambda service_type: services[service_type], lambda name: None, repository)
    monkeypatch.setattr(InfraHelper, "get_by_id_like", lambda model, identifier: recipient)
    monkeypatch.setattr(type(Env), "MAIL_SERVER", property(lambda self: "smtp.example.test"))
    monkeypatch.setattr(type(Env), "MAIL_FROM", property(lambda self: "noreply@example.test"))

    assert service.recover_pending_email_delivery() == int(smtp_accepted)

    email_service.prepare_template_message.assert_called_once_with("en-US", recipient.email, "assigned_to_card", {})
    repository.notification_email_delivery.begin_sending.assert_called_once_with(delivery)
    email_service.send_message.assert_called_once_with(email_service.prepare_template_message.return_value, strict=True)
    assert repository.notification_email_delivery.complete_sending.call_args.args[:2] == (
        delivery,
        expected_status,
    )


def test_email_recovery_does_not_claim_without_smtp_configuration(monkeypatch: MonkeyPatch) -> None:
    repository = Mock()
    service = NotificationService(lambda service_type: None, lambda name: None, repository)
    monkeypatch.setattr(type(Env), "MAIL_SERVER", property(lambda self: ""))

    assert service.recover_pending_email_delivery() == 0

    repository.notification_email_delivery.mark_stale_uncertain.assert_called_once()
    repository.notification_email_delivery.claim_pending.assert_not_called()


@pytest.mark.parametrize("failure", ["recipient_lookup", "template_render", "lost_claim"])
def test_email_recovery_does_not_send_before_sending_transition(monkeypatch: MonkeyPatch, failure: str) -> None:
    recipient = _user(2)
    delivery = NotificationEmailDelivery.model_construct(
        id=SnowflakeID(4),
        receiver_id=recipient.id,
        notification_type=NotificationType.ProjectInvited,
        scope_models=None,
        recipient_email=recipient.email,
        preferred_lang="en-US",
        template_name="assigned_to_card",
        formats={},
    )
    repository = Mock()
    repository.notification_email_delivery.claim_pending.return_value = [delivery]
    if failure == "lost_claim":
        repository.notification_email_delivery.begin_sending.return_value = False
    settings = Mock()
    settings.has_unsubscription.return_value = False
    email_service = Mock()
    if failure == "template_render":
        email_service.prepare_template_message.side_effect = ValueError("broken template")
    services = {UserNotificationSettingService: settings, EmailService: email_service}
    service = NotificationService(lambda service_type: services[service_type], lambda name: None, repository)
    lookup = (
        Mock(side_effect=RuntimeError("database unavailable"))
        if failure == "recipient_lookup"
        else Mock(return_value=recipient)
    )
    monkeypatch.setattr(InfraHelper, "get_by_id_like", lookup)
    monkeypatch.setattr(type(Env), "MAIL_SERVER", property(lambda self: "smtp.example.test"))
    monkeypatch.setattr(type(Env), "MAIL_FROM", property(lambda self: "noreply@example.test"))

    assert service.recover_pending_email_delivery() == 0

    email_service.send_message.assert_not_called()
    if failure == "lost_claim":
        repository.notification_email_delivery.complete_preparing.assert_not_called()
        repository.notification_email_delivery.complete_sending.assert_not_called()
    else:
        expected = (
            NotificationEmailDeliveryStatus.Pending
            if failure == "recipient_lookup"
            else NotificationEmailDeliveryStatus.Failed
        )
        assert repository.notification_email_delivery.complete_preparing.call_args.args[:2] == (delivery, expected)
        repository.notification_email_delivery.begin_sending.assert_not_called()


@pytest.mark.parametrize("reason", ["missing", "changed_email", "unsubscribed"])
def test_email_recovery_suppresses_ineligible_recipient(monkeypatch: MonkeyPatch, reason: str) -> None:
    recipient = _user(2)
    delivery = NotificationEmailDelivery.model_construct(
        id=SnowflakeID(4),
        receiver_id=recipient.id,
        notification_type=NotificationType.ProjectInvited,
        scope_models=None,
        recipient_email="old@example.test" if reason == "changed_email" else recipient.email,
    )
    repository = Mock()
    repository.notification_email_delivery.claim_pending.return_value = [delivery]
    settings = Mock()
    settings.has_unsubscription.return_value = reason == "unsubscribed"
    email_service = Mock()
    services = {UserNotificationSettingService: settings, EmailService: email_service}
    service = NotificationService(lambda service_type: services[service_type], lambda name: None, repository)
    monkeypatch.setattr(
        InfraHelper, "get_by_id_like", lambda model, identifier: None if reason == "missing" else recipient
    )
    monkeypatch.setattr(type(Env), "MAIL_SERVER", property(lambda self: "smtp.example.test"))
    monkeypatch.setattr(type(Env), "MAIL_FROM", property(lambda self: "noreply@example.test"))

    assert service.recover_pending_email_delivery() == 0

    assert repository.notification_email_delivery.complete_preparing.call_args.args[:2] == (
        delivery,
        NotificationEmailDeliveryStatus.Suppressed,
    )
    email_service.send_message.assert_not_called()
    repository.notification_email_delivery.begin_sending.assert_not_called()


def test_failed_web_fanout_batch_does_not_starve_later_notifications(monkeypatch: MonkeyPatch) -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    User.__table__.create(engine)
    UserNotification.__table__.create(engine)
    monkeypatch.setattr(DbEngine, "get_main_engine", lambda: engine)
    repository = UserNotificationRepository(lambda repository_type: None, lambda name: None)
    original_time = SafeDateTime.now() - timedelta(days=1)
    notifications = [
        UserNotification(
            notifier_type="user",
            notifier_id=SnowflakeID(1),
            receiver_id=SnowflakeID(2),
            notification_type=NotificationType.ProjectInvited,
            record_list=[],
            web_fanout_pending=True,
            created_at=original_time,
            updated_at=original_time,
        )
        for _ in range(3)
    ]
    repository.insert(notifications)
    notifications.sort(key=lambda notification: int(notification.id))
    cutoff = SafeDateTime.now() - timedelta(seconds=30)

    first_batch = repository.get_pending_web_fanout(cutoff, 2)
    assert [notification.id for notification in first_batch] == [notification.id for notification in notifications[:2]]
    for notification in first_batch:
        repository.defer_web_fanout(notification)

    assert [notification.id for notification in repository.get_pending_web_fanout(cutoff, 2)] == [notifications[2].id]
    assert [
        notification.id for notification in repository.get_pending_web_fanout(SafeDateTime.now() + timedelta(days=1), 3)
    ] == [
        notifications[2].id,
        notifications[0].id,
        notifications[1].id,
    ]
    engine.dispose()


def test_specific_unsubscription_query_includes_scope_type(monkeypatch: MonkeyPatch) -> None:
    statements = []
    database = Mock()

    def execute(statement):
        statements.append(statement)
        return Mock(first=lambda: None)

    database.exec.side_effect = execute

    @contextmanager
    def use(readonly: bool):
        assert readonly
        yield database

    monkeypatch.setattr(DbSession, "use", use)
    repository = UserNotificationSettingRepository(lambda repository_type: None, lambda name: None)
    repository.get_unsubscriptions_query_builder(_user(2)).where_channel(
        NotificationChannel.Web
    ).where_notification_type(NotificationType.ProjectInvited).where_scope(
        NotificationScope.Specific, ("project", 3)
    ).first()

    assert len(statements) == 1
    statement = str(statements[0])
    assert "scope_type" in statement
    assert "specific_table" in statement
    assert "specific_id" in statement
