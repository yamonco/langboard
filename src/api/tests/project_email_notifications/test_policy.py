import os
from types import SimpleNamespace
from unittest.mock import Mock
import pytest
from sqlalchemy import create_engine


os.environ.setdefault("PROJECT_NAME", "langboard")

from langboard_shared.core.db.DbEngine import DbEngine  # noqa: E402
from langboard_shared.core.types import SnowflakeID  # noqa: E402
from langboard_shared.domain.models import (  # noqa: E402  # noqa: E402
    Project,
    ProjectActivity,
    ProjectAssignedUser,
    ProjectEmailNotificationRecipient,
    User,
)
from langboard_shared.domain.models.ProjectActivity import ProjectActivityType  # noqa: E402
from langboard_shared.domain.models.ProjectEmailNotificationPolicy import (  # noqa: E402
    ProjectEmailNotificationCategory,
    ProjectEmailNotificationPolicy,
)
from langboard_shared.domain.services.factory.ProjectEmailNotificationService import (  # noqa: E402
    ProjectEmailDeliveryRecipient,
    ProjectEmailNotificationService,
)
from langboard_shared.helpers import InfraHelper  # noqa: E402
from langboard_shared.infrastructure.repositories.factory.ProjectAssignedUserRepository import (  # noqa: E402
    ProjectAssignedUserRepository,
)
from langboard_shared.infrastructure.repositories.factory.ProjectEmailNotificationRepository import (  # noqa: E402
    ProjectEmailNotificationRepository,
)
from langboard_shared.tasks.activities import ProjectActivityTask  # noqa: E402


def _card_moved_activity(column: str) -> ProjectActivity:
    return ProjectActivity(
        project_id=1,
        project_column_id=2,
        card_id=3,
        user_id=4,
        activity_type=ProjectActivityType.CardMoved,
        activity_history={"card": {"title": "Release"}, "column": {"name": column}},
    )


def test_si_target_column_matches_review_only() -> None:
    policy = ProjectEmailNotificationPolicy(
        project_id=1,
        is_enabled=True,
        notify_all_members=True,
        categories=[ProjectEmailNotificationCategory.Cards],
        card_move_target_columns=["Review"],
    )

    assert ProjectEmailNotificationService._matches_card_move_target(_card_moved_activity("Review"), policy)
    assert not ProjectEmailNotificationService._matches_card_move_target(_card_moved_activity("Done"), policy)


def test_empty_target_columns_preserve_category_wide_notifications() -> None:
    policy = ProjectEmailNotificationPolicy(
        project_id=1,
        is_enabled=True,
        categories=[ProjectEmailNotificationCategory.Comments],
    )
    assert ProjectEmailNotificationService._matches_card_move_target(_card_moved_activity("Done"), policy)
    assert (
        ProjectEmailNotificationService.category_for_activity(ProjectActivityType.CardCommentAdded.value)
        == ProjectEmailNotificationCategory.Comments
    )


def test_target_columns_do_not_suppress_non_move_notifications() -> None:
    policy = ProjectEmailNotificationPolicy(
        project_id=1,
        is_enabled=True,
        categories=[ProjectEmailNotificationCategory.Comments],
        card_move_target_columns=["Review"],
    )
    activity = ProjectActivity(
        project_id=1,
        card_id=3,
        user_id=4,
        activity_type=ProjectActivityType.CardCommentAdded,
        activity_history={"card": {"title": "Release"}},
    )

    assert ProjectEmailNotificationService._matches_card_move_target(activity, policy)


def test_update_response_uses_written_policy_when_read_replica_is_stale(monkeypatch: pytest.MonkeyPatch) -> None:
    written: dict[str, object] = {}
    recorded: list[tuple[object, object, int, int]] = []
    project = SimpleNamespace(id=1)
    actor = SimpleNamespace(id=4)
    repository = SimpleNamespace(
        project_column=SimpleNamespace(
            get_all_by_project=lambda _project: [(SimpleNamespace(name="Review", is_archive=False), 0)]
        ),
        project_assigned_user=SimpleNamespace(get_all_by_project=lambda _project, _ids: []),
        project_email_notification=SimpleNamespace(
            replace=lambda _project, **values: (written.update(values), ["old@example.com"]),
        ),
    )
    service = ProjectEmailNotificationService(lambda _service: None, lambda _name: None, repository)
    monkeypatch.setattr(InfraHelper, "get_by_id_like", lambda _model, _project: project)
    monkeypatch.setattr(
        ProjectActivityTask,
        "project_email_notification_policy_updated",
        lambda *args: recorded.append(args),
    )
    monkeypatch.setattr(
        service,
        "get_api_policy",
        lambda _project: {
            "is_enabled": False,
            "notify_all_members": False,
            "categories": ["comments"],
            "card_move_target_columns": [],
            "recipient_user_uids": [],
        },
    )

    response = service.update_policy(
        project,
        is_enabled=True,
        notify_all_members=True,
        categories=[ProjectEmailNotificationCategory.Cards],
        recipient_user_uids=[],
        card_move_target_columns=["Review"],
        external_recipient_emails=[" Customer@Example.com ", "customer@example.com"],
        actor=actor,
    )

    assert response == {
        "is_enabled": True,
        "notify_all_members": True,
        "categories": ["cards"],
        "card_move_target_columns": ["Review"],
        "recipient_user_uids": [],
        "external_recipient_emails": ["customer@example.com"],
    }
    assert written["notify_all_members"] is True
    assert written["external_recipient_emails"] == ["customer@example.com"]
    assert recorded == [(actor, project, 1, 1)]


def test_invalid_external_email_is_rejected() -> None:
    with pytest.raises(ValueError, match="external email"):
        ProjectEmailNotificationService._normalize_external_emails(["not-an-email"])


def test_delivery_recipients_merge_members_and_external_addresses(monkeypatch: pytest.MonkeyPatch) -> None:
    actor = SimpleNamespace(id=4, email="owner@example.com")
    member = SimpleNamespace(
        id=5,
        email="Customer@Example.com",
        preferred_lang="en-US",
        deleted_at=None,
        activated_at=object(),
    )
    policy = ProjectEmailNotificationPolicy(
        project_id=1,
        is_enabled=True,
        notify_all_members=True,
        categories=[ProjectEmailNotificationCategory.Cards],
        external_recipient_emails=["customer@example.com", "owner@example.com", "edge@example.com"],
    )
    repository = SimpleNamespace(
        project_email_notification=SimpleNamespace(get_with_recipients=lambda _project, **_kwargs: (policy, [])),
        project_assigned_user=SimpleNamespace(get_all_by_project=lambda _project: [(actor, None), (member, None)]),
    )
    service = ProjectEmailNotificationService(lambda _service: None, lambda _name: None, repository)
    monkeypatch.setattr(InfraHelper, "get_by_id_like", lambda _model, identifier: actor if identifier == 4 else None)

    recipients = service.get_delivery_recipients(_card_moved_activity("Review"))

    assert [(recipient.email, recipient.language) for recipient in recipients] == [
        ("customer@example.com", "en-US"),
        ("edge@example.com", "en-US"),
    ]


def test_single_delivery_revalidation_does_not_reload_all_project_members(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Each delivery task validates only its recipient instead of repeating fanout."""

    actor = SimpleNamespace(id=4, email="owner@example.com")
    member = SimpleNamespace(
        id=5,
        email="member@example.com",
        preferred_lang="en-GB",
        deleted_at=None,
        activated_at=object(),
    )
    policy = ProjectEmailNotificationPolicy(
        project_id=1,
        is_enabled=True,
        notify_all_members=True,
        categories=[ProjectEmailNotificationCategory.Cards],
    )
    policy_lookup = Mock(return_value=(policy, []))
    assignment_lookup = Mock(return_value=object())
    repository = SimpleNamespace(
        project_email_notification=SimpleNamespace(get_with_recipients=policy_lookup),
        project_assigned_user=SimpleNamespace(
            get_all_by_project=lambda *_args: (_ for _ in ()).throw(AssertionError("bulk member query")),
            get_by_user_and_project=assignment_lookup,
        ),
        user=SimpleNamespace(get_by_email=lambda _email: (member, None)),
    )
    service = ProjectEmailNotificationService(lambda _service: None, lambda _name: None, repository)
    monkeypatch.setattr(InfraHelper, "get_by_id_like", lambda _model, identifier: actor if identifier == 4 else None)

    recipient = service._get_delivery_recipient(_card_moved_activity("Review"), "MEMBER@example.com")

    assert recipient is not None
    assert recipient.email == "member@example.com"
    assert recipient.language == "en-GB"
    policy_lookup.assert_called_once_with(1, consistent=True)
    assignment_lookup.assert_called_once_with(member, 1, consistent=True)


def test_email_delivery_revalidation_reads_current_policy_and_membership(monkeypatch: pytest.MonkeyPatch) -> None:
    main = create_engine("sqlite+pysqlite:///:memory:")
    replica = create_engine("sqlite+pysqlite:///:memory:")
    for engine in (main, replica):
        User.__table__.create(engine)
        ProjectEmailNotificationPolicy.__table__.create(engine)
        ProjectEmailNotificationRecipient.__table__.create(engine)
        ProjectAssignedUser.__table__.create(engine)
    monkeypatch.setattr(DbEngine, "get_main_engine", lambda: main)
    monkeypatch.setattr(DbEngine, "get_readonly_engine", lambda: replica)

    policy_repo = ProjectEmailNotificationRepository(lambda _type: None, lambda _name: None)
    assignment_repo = ProjectAssignedUserRepository(lambda _type: None, lambda _name: None)
    current_policy = ProjectEmailNotificationPolicy(
        project_id=SnowflakeID(1),
        is_enabled=True,
        notify_all_members=True,
        categories=[ProjectEmailNotificationCategory.Cards],
    )
    policy_repo.insert(current_policy)
    assignment = ProjectAssignedUser(project_id=SnowflakeID(1), user_id=SnowflakeID(5))
    assignment_repo.insert(assignment)

    assert policy_repo.get_with_recipients(1)[0] is None
    assert policy_repo.get_with_recipients(1, consistent=True)[0] is not None
    assert assignment_repo.get_by_user_and_project(5, 1) is None
    assert assignment_repo.get_by_user_and_project(5, 1, consistent=True) is not None

    main.dispose()
    replica.dispose()


def test_email_delivery_ignores_stale_enabled_replica_policy(monkeypatch: pytest.MonkeyPatch) -> None:
    main = create_engine("sqlite+pysqlite:///:memory:")
    replica = create_engine("sqlite+pysqlite:///:memory:")
    for engine in (main, replica):
        User.__table__.create(engine)
        ProjectEmailNotificationPolicy.__table__.create(engine)
        ProjectEmailNotificationRecipient.__table__.create(engine)
    monkeypatch.setattr(DbEngine, "get_main_engine", lambda: main)
    monkeypatch.setattr(DbEngine, "get_readonly_engine", lambda: replica)
    policy_repo = ProjectEmailNotificationRepository(lambda _type: None, lambda _name: None)
    policy_repo.insert(
        ProjectEmailNotificationPolicy(
            project_id=SnowflakeID(1), is_enabled=False, categories=[ProjectEmailNotificationCategory.Cards]
        )
    )
    with monkeypatch.context() as replica_write:
        replica_write.setattr(DbEngine, "get_main_engine", lambda: replica)
        policy_repo.insert(
            ProjectEmailNotificationPolicy(
                project_id=SnowflakeID(1),
                is_enabled=True,
                categories=[ProjectEmailNotificationCategory.Cards],
                external_recipient_emails=["outside@example.com"],
            )
        )

    repository = SimpleNamespace(project_email_notification=policy_repo)
    service = ProjectEmailNotificationService(lambda _type: None, lambda _name: None, repository)
    monkeypatch.setattr(InfraHelper, "get_by_id_like", lambda *_args: None)

    assert policy_repo.get_with_recipients(1)[0].is_enabled is True
    assert service._get_delivery_recipient(_card_moved_activity("Review"), "outside@example.com") is None
    assert service.send_activity_email(_card_moved_activity("Review"), "outside@example.com") is None

    main.dispose()
    replica.dispose()


def test_activity_email_requires_confirmed_smtp_acceptance(monkeypatch: pytest.MonkeyPatch) -> None:
    activity = _card_moved_activity("Review")
    project = Project.model_construct(id=1, title="Project")
    email_service = Mock()
    email_service.send_message.return_value = False
    service = ProjectEmailNotificationService(lambda _service: email_service, lambda _name: None, Mock())
    monkeypatch.setattr(
        service,
        "_get_delivery_recipient",
        lambda *_args: ProjectEmailDeliveryRecipient(email="member@example.com", language="en-US"),
    )
    monkeypatch.setattr(InfraHelper, "get_by_id_like", lambda model, _identifier: project if model is Project else None)
    monkeypatch.setattr(service, "_get_activity_notifier", lambda _activity: SimpleNamespace(name="Sender"))
    monkeypatch.setattr(service, "_project_owner_email", lambda _project: None)
    monkeypatch.setattr(service, "_create_redirect_url", lambda *_args: "https://example.test/card")

    assert service.send_activity_email(activity, "member@example.com") is False
    email_service.prepare_template_message.assert_called_once()
    assert email_service.send_message.call_args.kwargs["strict"] is True
