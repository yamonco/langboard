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
    project = SimpleNamespace(id=1)
    repository = SimpleNamespace(
        project_column=SimpleNamespace(
            get_all_by_project=lambda _project: [(SimpleNamespace(name="Review", is_archive=False), 0)]
        ),
        project_assigned_user=SimpleNamespace(get_all_by_project=lambda _project, _ids: []),
        project_email_notification=SimpleNamespace(replace=lambda _project, **values: written.update(values)),
    )
    service = ProjectEmailNotificationService(lambda _service: None, lambda _name: None, repository)
    monkeypatch.setattr(InfraHelper, "get_by_id_like", lambda _model, _project: project)
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
    )

    assert response == {
        "is_enabled": True,
        "notify_all_members": True,
        "categories": ["cards"],
        "card_move_target_columns": ["Review"],
        "recipient_user_uids": [],
    }
    assert written["notify_all_members"] is True
