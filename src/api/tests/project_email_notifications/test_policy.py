import os


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
