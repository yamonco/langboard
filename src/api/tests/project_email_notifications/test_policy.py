import os
from types import SimpleNamespace
import pytest


os.environ.setdefault("PROJECT_NAME", "langboard")

from langboard_shared.domain.models import ProjectActivity  # noqa: E402
from langboard_shared.domain.models.ProjectActivity import ProjectActivityType  # noqa: E402
from langboard_shared.domain.models.ProjectEmailNotificationPolicy import (  # noqa: E402
    ProjectEmailNotificationCategory,
    ProjectEmailNotificationPolicy,
)
from langboard_shared.domain.services.factory.ProjectEmailNotificationService import (  # noqa: E402
    ProjectEmailNotificationService,
)
from langboard_shared.helpers import InfraHelper  # noqa: E402
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


def test_update_response_uses_written_policy_when_read_replica_is_stale(monkeypatch: pytest.MonkeyPatch) -> None:
    written: dict[str, object] = {}
    recorded: list[tuple[object, object, list[str], list[str]]] = []
    project = SimpleNamespace(id=1)
    actor = SimpleNamespace(id=4)
    repository = SimpleNamespace(
        project_column=SimpleNamespace(
            get_all_by_project=lambda _project: [(SimpleNamespace(name="Review", is_archive=False), 0)]
        ),
        project_assigned_user=SimpleNamespace(get_all_by_project=lambda _project, _ids: []),
        project_email_notification=SimpleNamespace(
            get_with_recipients=lambda _project: (None, []),
            replace=lambda _project, **values: written.update(values),
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
    assert recorded == [(actor, project, ["customer@example.com"], [])]


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
        project_email_notification=SimpleNamespace(get_with_recipients=lambda _project: (policy, [])),
        project_assigned_user=SimpleNamespace(get_all_by_project=lambda _project: [(actor, None), (member, None)]),
    )
    service = ProjectEmailNotificationService(lambda _service: None, lambda _name: None, repository)
    monkeypatch.setattr(InfraHelper, "get_by_id_like", lambda _model, identifier: actor if identifier == 4 else None)

    recipients = service.get_delivery_recipients(_card_moved_activity("Review"))

    assert [(recipient.email, recipient.language) for recipient in recipients] == [
        ("customer@example.com", "en-US"),
        ("edge@example.com", "en-US"),
    ]
