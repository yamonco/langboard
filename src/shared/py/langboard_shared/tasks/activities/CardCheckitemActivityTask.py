from ...core.broker import Broker
from ...domain.models import Bot, Card, Checkitem, Project, ProjectActivity, User
from ...domain.models.ProjectActivity import ProjectActivityType
from .UserActivityTask import record_project_activity
from .utils import ActivityHistoryHelper, ActivityTaskHelper


@Broker.wrap_async_task_decorator
async def card_checkitem_created(user_or_bot: User | Bot, project: Project, card: Card, checkitem: Checkitem):
    helper = ActivityTaskHelper(ProjectActivity)
    activity_history = _get_default_history(helper, project, card, checkitem)
    activity = helper.record(
        user_or_bot,
        activity_history,
        **_get_activity_params(ProjectActivityType.CardCheckitemCreated, project, card),
    )
    record_project_activity(user_or_bot, activity)


@Broker.wrap_async_task_decorator
async def card_checkitem_title_changed(
    user_or_bot: User | Bot, project: Project, card: Card, old_title: str, checkitem: Checkitem
):
    helper = ActivityTaskHelper(ProjectActivity)
    activity_history = {
        **_get_default_history(helper, project, card, checkitem),
        "changes": {"before": {"title": old_title}, "after": {"title": checkitem.title}},
    }
    activity = helper.record(
        user_or_bot,
        activity_history,
        **_get_activity_params(ProjectActivityType.CardCheckitemTitleChanged, project, card),
    )
    record_project_activity(user_or_bot, activity)


@Broker.wrap_async_task_decorator
async def card_checkitem_timer_started(user_or_bot: User | Bot, project: Project, card: Card, checkitem: Checkitem):
    helper = ActivityTaskHelper(ProjectActivity)
    activity_history = _get_default_history(helper, project, card, checkitem)
    activity = helper.record(
        user_or_bot,
        activity_history,
        **_get_activity_params(ProjectActivityType.CardCheckitemTimerStarted, project, card),
    )
    record_project_activity(user_or_bot, activity)


@Broker.wrap_async_task_decorator
async def card_checkitem_timer_paused(user_or_bot: User | Bot, project: Project, card: Card, checkitem: Checkitem):
    helper = ActivityTaskHelper(ProjectActivity)
    activity_history = _get_default_history(helper, project, card, checkitem)
    activity = helper.record(
        user_or_bot,
        activity_history,
        **_get_activity_params(ProjectActivityType.CardCheckitemTimerPaused, project, card),
    )
    record_project_activity(user_or_bot, activity)


@Broker.wrap_async_task_decorator
async def card_checkitem_timer_stopped(user_or_bot: User | Bot, project: Project, card: Card, checkitem: Checkitem):
    helper = ActivityTaskHelper(ProjectActivity)
    activity_history = _get_default_history(helper, project, card, checkitem)
    activity = helper.record(
        user_or_bot,
        activity_history,
        **_get_activity_params(ProjectActivityType.CardCheckitemTimerStopped, project, card),
    )
    record_project_activity(user_or_bot, activity)


@Broker.wrap_async_task_decorator
async def card_checkitem_checked(user_or_bot: User | Bot, project: Project, card: Card, checkitem: Checkitem):
    helper = ActivityTaskHelper(ProjectActivity)
    activity_history = _get_default_history(helper, project, card, checkitem)
    activity = helper.record(
        user_or_bot,
        activity_history,
        **_get_activity_params(ProjectActivityType.CardCheckitemChecked, project, card),
    )
    record_project_activity(user_or_bot, activity)


@Broker.wrap_async_task_decorator
async def card_checkitem_unchecked(user_or_bot: User | Bot, project: Project, card: Card, checkitem: Checkitem):
    helper = ActivityTaskHelper(ProjectActivity)
    activity_history = _get_default_history(helper, project, card, checkitem)
    activity = helper.record(
        user_or_bot,
        activity_history,
        **_get_activity_params(ProjectActivityType.CardCheckitemUnchecked, project, card),
    )
    record_project_activity(user_or_bot, activity)


@Broker.wrap_async_task_decorator
async def card_checkitem_cardified(user_or_bot: User | Bot, project: Project, card: Card, checkitem: Checkitem):
    helper = ActivityTaskHelper(ProjectActivity)
    activity_history = {
        **_get_default_history(helper, project, card, checkitem),
        "record_ids": [(checkitem.cardified_id, "cardified_card")],
    }
    activity = helper.record(
        user_or_bot,
        activity_history,
        **_get_activity_params(ProjectActivityType.CardCheckitemDeleted, project, card),
    )
    record_project_activity(user_or_bot, activity)


@Broker.wrap_async_task_decorator
async def card_checkitem_deleted(user_or_bot: User | Bot, project: Project, card: Card, checkitem: Checkitem):
    helper = ActivityTaskHelper(ProjectActivity)
    activity_history = _get_default_history(helper, project, card, checkitem)
    activity = helper.record(
        user_or_bot,
        activity_history,
        **_get_activity_params(ProjectActivityType.CardCheckitemDeleted, project, card),
    )
    record_project_activity(user_or_bot, activity)


def _get_default_history(helper: ActivityTaskHelper, project: Project, card: Card, checkitem: Checkitem):
    return {
        **helper.create_project_default_history(project, card=card),
        "checkitem": ActivityHistoryHelper.create_checklist_or_checkitem_history(checkitem),
    }


def _get_activity_params(activity_type: ProjectActivityType, project: Project, card: Card):
    activity_params = {
        "activity_type": activity_type,
        "project_id": project.id,
        "project_column_id": card.project_column_id,
        "card_id": card.id,
    }

    return activity_params
