from datetime import timedelta
import pytest
from langboard_shared.core.db.DbEngine import DbEngine
from langboard_shared.core.types import SafeDateTime, SnowflakeID
from langboard_shared.domain.models import ProjectActivity, ProjectActivityEmailDelivery, ProjectWikiActivity
from langboard_shared.domain.models.NotificationEmailDelivery import NotificationEmailDeliveryStatus
from langboard_shared.domain.models.ProjectActivity import ProjectActivityType
from langboard_shared.domain.models.ProjectWikiActivity import ProjectWikiActivityType
from langboard_shared.domain.services.factory.ProjectEmailNotificationService import ProjectEmailNotificationService
from langboard_shared.infrastructure.repositories.factory.ProjectActivityEmailDeliveryRepository import (
    ProjectActivityEmailDeliveryRepository,
)
from langboard_shared.infrastructure.repositories.Repository import Repository
from sqlalchemy import create_engine


@pytest.fixture
def delivery_repository(monkeypatch: pytest.MonkeyPatch):
    engine = create_engine("sqlite+pysqlite:///:memory:")
    ProjectActivity.__table__.create(engine)
    ProjectWikiActivity.__table__.create(engine)
    ProjectActivityEmailDelivery.__table__.create(engine)
    monkeypatch.setattr(DbEngine, "get_main_engine", lambda: engine)
    with engine.begin() as connection:
        connection.execute(
            ProjectActivity.__table__.insert().values(
                id=SnowflakeID(1),
                project_id=SnowflakeID(2),
                activity_type=ProjectActivityType.CardCreated,
                activity_history={},
                email_fanout_pending=True,
            )
        )
        connection.execute(
            ProjectActivity.__table__.insert().values(
                id=SnowflakeID(3),
                project_id=SnowflakeID(2),
                activity_type=ProjectActivityType.CardCreated,
                activity_history={},
                email_fanout_pending=None,
            )
        )
        connection.execute(
            ProjectWikiActivity.__table__.insert().values(
                id=SnowflakeID(4),
                project_id=SnowflakeID(2),
                project_wiki_id=SnowflakeID(5),
                activity_type=ProjectWikiActivityType.WikiCreated,
                activity_history={},
                email_fanout_pending=True,
            )
        )
    yield ProjectActivityEmailDeliveryRepository(lambda repository_type: None, lambda name: None)
    engine.dispose()


def _activity() -> ProjectActivity:
    return ProjectActivity.model_construct(id=SnowflakeID(1), project_id=SnowflakeID(2))


def test_fanout_freezes_recipients_after_legacy_delivery(
    delivery_repository: ProjectActivityEmailDeliveryRepository,
) -> None:
    repository = delivery_repository
    activity = _activity()

    legacy = repository.accept_one(activity, "FIRST@example.test")
    assert legacy is not None
    deliveries = repository.accept_recipients(activity, ["FIRST@example.test", "second@example.test"])
    assert {delivery.recipient_email for delivery in deliveries} == {"first@example.test", "second@example.test"}

    replay = repository.accept_recipients(activity, ["third@example.test"])
    assert {delivery.recipient_email for delivery in replay} == {"first@example.test", "second@example.test"}
    assert repository.accept_one(activity, "third@example.test") is None


def test_empty_fanout_remains_empty_on_replay(delivery_repository: ProjectActivityEmailDeliveryRepository) -> None:
    repository = delivery_repository
    activity = _activity()

    assert repository.accept_recipients(activity, []) == []
    assert repository.accept_recipients(activity, ["later@example.test"]) == []


def test_recovery_finds_only_new_unaccepted_activities(
    delivery_repository: ProjectActivityEmailDeliveryRepository,
) -> None:
    repository = delivery_repository
    activity = _activity()

    assert {(record.__tablename__, record.id) for record in repository.get_pending_fanout(8)} == {
        (ProjectActivity.__tablename__, SnowflakeID(1)),
        (ProjectWikiActivity.__tablename__, SnowflakeID(4)),
    }
    assert repository.accept_recipients(activity, []) == []
    assert [(record.__tablename__, record.id) for record in repository.get_pending_fanout(8)] == [
        (ProjectWikiActivity.__tablename__, SnowflakeID(4))
    ]


def test_new_activity_models_default_to_pending_email_fanout() -> None:
    assert ProjectActivity(
        project_id=SnowflakeID(2), activity_type=ProjectActivityType.CardCreated
    ).email_fanout_pending


def test_failed_fanout_deferral_allows_later_activity_then_retries(
    delivery_repository: ProjectActivityEmailDeliveryRepository,
) -> None:
    repository = delivery_repository
    with DbEngine.get_main_engine().begin() as connection:
        connection.execute(
            ProjectActivity.__table__.insert().values(
                id=SnowflakeID(6),
                project_id=SnowflakeID(2),
                activity_type=ProjectActivityType.CardCreated,
                activity_history={},
                email_fanout_pending=True,
            )
        )

    first = next(record for record in repository.get_pending_fanout(1) if isinstance(record, ProjectActivity))
    assert first.id == SnowflakeID(1)
    repository.defer_pending_fanout(first)
    next_board = next(record for record in repository.get_pending_fanout(1) if isinstance(record, ProjectActivity))
    assert next_board.id == SnowflakeID(6)

    with DbEngine.get_main_engine().begin() as connection:
        connection.execute(
            ProjectActivity.__table__.update()
            .where(ProjectActivity.__table__.c.id == first.id)
            .values(email_fanout_retry_at=SafeDateTime.now() - timedelta(seconds=1))
        )
    retried = next(record for record in repository.get_pending_fanout(1) if isinstance(record, ProjectActivity))
    assert retried.id == first.id
    assert ProjectWikiActivity(
        project_id=SnowflakeID(2),
        project_wiki_id=SnowflakeID(5),
        activity_type=ProjectWikiActivityType.WikiCreated,
    ).email_fanout_pending


def test_due_retries_do_not_starve_first_attempts_beyond_batch_size(
    delivery_repository: ProjectActivityEmailDeliveryRepository,
) -> None:
    now = SafeDateTime.now()
    with DbEngine.get_main_engine().begin() as connection:
        connection.execute(
            ProjectActivity.__table__.update()
            .where(ProjectActivity.__table__.c.id == SnowflakeID(1))
            .values(email_fanout_pending=False)
        )
        connection.execute(
            ProjectActivity.__table__.insert(),
            [
                {
                    "id": SnowflakeID(activity_id),
                    "project_id": SnowflakeID(2),
                    "activity_type": ProjectActivityType.CardCreated,
                    "activity_history": {},
                    "email_fanout_pending": True,
                    "created_at": now - timedelta(hours=1),
                    "email_fanout_retry_at": now - timedelta(seconds=1),
                }
                for activity_id in range(10, 60)
            ],
        )
        connection.execute(
            ProjectActivity.__table__.insert().values(
                id=SnowflakeID(60),
                project_id=SnowflakeID(2),
                activity_type=ProjectActivityType.CardCreated,
                activity_history={},
                email_fanout_pending=True,
                created_at=now - timedelta(minutes=30),
            )
        )

    board_batch = [
        activity.id for activity in delivery_repository.get_pending_fanout(8) if isinstance(activity, ProjectActivity)
    ]
    assert board_batch[0] == SnowflakeID(60)
    assert len(board_batch) == 8


def test_smtp_claim_and_review_require_explicit_transition(
    delivery_repository: ProjectActivityEmailDeliveryRepository,
) -> None:
    repository = delivery_repository
    delivery = repository.accept_recipients(_activity(), ["member@example.test"])[0]

    claimed = repository.claim_one(delivery.id)
    assert claimed is not None
    assert repository.claim_one(delivery.id) is None
    assert repository.begin_sending(claimed)
    assert repository.complete(claimed, NotificationEmailDeliveryStatus.Uncertain, "SMTP outcome unknown")
    assert repository.claim_one(delivery.id) is None
    assert repository.count_for_review() == 1
    assert repository.resolve_review_item(
        delivery.id,
        NotificationEmailDeliveryStatus.Uncertain,
        NotificationEmailDeliveryStatus.Pending,
        "Operator retry",
    )
    assert repository.claim_one(delivery.id) is not None


def test_terminal_purge_preserves_fanout_marker(delivery_repository: ProjectActivityEmailDeliveryRepository) -> None:
    repository = delivery_repository
    activity = _activity()
    delivery = repository.accept_recipients(activity, ["member@example.test"])[0]
    claimed = repository.claim_one(delivery.id)
    assert claimed is not None
    assert repository.complete(claimed, NotificationEmailDeliveryStatus.Suppressed)

    assert repository.purge_terminal_before(SafeDateTime.now() + timedelta(days=1), 10) == 1
    assert repository.accept_recipients(activity, ["new@example.test"]) == []
    assert repository.accept_one(activity, "new@example.test") is None


def test_uncertain_delivery_requires_operator_acknowledgement(
    delivery_repository: ProjectActivityEmailDeliveryRepository,
) -> None:
    repository = delivery_repository
    delivery = repository.accept_recipients(_activity(), ["member@example.test"])[0]
    claimed = repository.claim_one(delivery.id)
    assert claimed is not None
    assert repository.begin_sending(claimed)
    assert repository.complete(claimed, NotificationEmailDeliveryStatus.Uncertain, "SMTP outcome unknown")
    service = ProjectEmailNotificationService(lambda _service: None, lambda _name: None, Repository())

    with pytest.raises(ValueError, match="explicit acknowledgement"):
        service.resolve_delivery_review(delivery.id, "retry", "INC-123")
    assert repository.claim_one(delivery.id) is None
    assert service.resolve_delivery_review(delivery.id, "retry", "INC-123", acknowledge_uncertain=True)
    assert repository.claim_one(delivery.id) is not None
