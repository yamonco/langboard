from ...core.broker import Broker
from ...domain.models import Bot, Card, CardAttachment, Project, ProjectActivity, User
from ...domain.models.ProjectActivity import ProjectActivityType
from .UserActivityTask import record_project_activity
from .utils import ActivityHistoryHelper, ActivityTaskHelper


@Broker.wrap_async_task_decorator
async def card_attachment_uploaded(user_or_bot: User | Bot, project: Project, card: Card, attachment: CardAttachment):
    helper = ActivityTaskHelper(ProjectActivity)
    activity_history = _get_default_history(helper, project, card, attachment)
    activity = helper.record(
        user_or_bot,
        activity_history,
        **_get_activity_params(ProjectActivityType.CardAttachmentUploaded, project, card),
    )
    record_project_activity(user_or_bot, activity)


@Broker.wrap_async_task_decorator
async def card_attachment_name_changed(
    user_or_bot: User | Bot, project: Project, card: Card, old_name: str, attachment: CardAttachment
):
    helper = ActivityTaskHelper(ProjectActivity)
    activity_history = {
        **_get_default_history(helper, project, card, attachment),
        "changes": {"before": {"name": old_name}, "after": {"name": attachment.filename}},
    }
    activity = helper.record(
        user_or_bot,
        activity_history,
        **_get_activity_params(ProjectActivityType.CardAttachmentNameChanged, project, card),
    )
    record_project_activity(user_or_bot, activity)


@Broker.wrap_async_task_decorator
async def card_attachment_deleted(user_or_bot: User | Bot, project: Project, card: Card, attachment: CardAttachment):
    helper = ActivityTaskHelper(ProjectActivity)
    activity_history = _get_default_history(helper, project, card, attachment)
    activity = helper.record(
        user_or_bot,
        activity_history,
        **_get_activity_params(ProjectActivityType.ProjectLabelDeleted, project, card),
    )
    record_project_activity(user_or_bot, activity)


def _get_default_history(helper: ActivityTaskHelper, project: Project, card: Card, attachment: CardAttachment):
    return {
        **helper.create_project_default_history(project, card=card),
        "attachment": ActivityHistoryHelper.create_card_attachment_history(attachment),
    }


def _get_activity_params(activity_type: ProjectActivityType, project: Project, card: Card):
    activity_params = {
        "activity_type": activity_type,
        "project_id": project.id,
        "project_column_id": card.project_column_id,
        "card_id": card.id,
    }

    return activity_params
