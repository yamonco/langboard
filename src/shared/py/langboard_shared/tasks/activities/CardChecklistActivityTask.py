from ...core.broker import Broker
from ...domain.models import Bot, Card, Checklist, Project, ProjectActivity, User
from ...domain.models.ProjectActivity import ProjectActivityType
from . import UserActivityTask
from .utils import ActivityHistoryHelper, ActivityTaskHelper


@Broker.wrap_async_task_decorator
async def card_checklist_created(user_or_bot: User | Bot, project: Project, card: Card, checklist: Checklist):
    helper = ActivityTaskHelper(ProjectActivity)
    activity_history = _get_default_history(helper, project, card, checklist)
    activity = helper.record(
        user_or_bot,
        activity_history,
        **_get_activity_params(ProjectActivityType.CardChecklistCreated, project, card),
    )
    UserActivityTask.record_project_activity(user_or_bot, activity)


@Broker.wrap_async_task_decorator
async def card_checklist_title_changed(
    user_or_bot: User | Bot, project: Project, card: Card, old_title: str, checklist: Checklist
):
    helper = ActivityTaskHelper(ProjectActivity)
    activity_history = {
        **_get_default_history(helper, project, card, checklist),
        "changes": {"before": {"title": old_title}, "after": {"title": checklist.title}},
    }
    activity = helper.record(
        user_or_bot,
        activity_history,
        **_get_activity_params(ProjectActivityType.CardChecklistTitleChanged, project, card),
    )
    UserActivityTask.record_project_activity(user_or_bot, activity)


@Broker.wrap_async_task_decorator
async def card_checklist_checked(user_or_bot: User | Bot, project: Project, card: Card, checklist: Checklist):
    helper = ActivityTaskHelper(ProjectActivity)
    activity_history = _get_default_history(helper, project, card, checklist)
    activity = helper.record(
        user_or_bot,
        activity_history,
        **_get_activity_params(ProjectActivityType.CardChecklistChecked, project, card),
    )
    UserActivityTask.record_project_activity(user_or_bot, activity)


@Broker.wrap_async_task_decorator
async def card_checklist_unchecked(user_or_bot: User | Bot, project: Project, card: Card, checklist: Checklist):
    helper = ActivityTaskHelper(ProjectActivity)
    activity_history = _get_default_history(helper, project, card, checklist)
    activity = helper.record(
        user_or_bot,
        activity_history,
        **_get_activity_params(ProjectActivityType.CardChecklistUnchecked, project, card),
    )
    UserActivityTask.record_project_activity(user_or_bot, activity)


@Broker.wrap_async_task_decorator
async def card_checklist_deleted(user_or_bot: User | Bot, project: Project, card: Card, checklist: Checklist):
    helper = ActivityTaskHelper(ProjectActivity)
    activity_history = _get_default_history(helper, project, card, checklist)
    activity = helper.record(
        user_or_bot,
        activity_history,
        **_get_activity_params(ProjectActivityType.CardChecklistDeleted, project, card),
    )
    UserActivityTask.record_project_activity(user_or_bot, activity)


def _get_default_history(helper: ActivityTaskHelper, project: Project, card: Card, checklist: Checklist):
    return {
        **helper.create_project_default_history(project, card=card),
        "checklist": ActivityHistoryHelper.create_checklist_or_checkitem_history(checklist),
    }


def _get_activity_params(activity_type: ProjectActivityType, project: Project, card: Card):
    activity_params = {
        "activity_type": activity_type,
        "project_id": project.id,
        "project_column_id": card.project_column_id,
        "card_id": card.id,
    }

    return activity_params
