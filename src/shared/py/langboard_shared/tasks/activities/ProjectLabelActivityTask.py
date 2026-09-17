from typing import Any
from ...core.broker import Broker
from ...domain.models import Bot, Project, ProjectActivity, ProjectLabel, User
from ...domain.models.ProjectActivity import ProjectActivityType
from .UserActivityTask import record_project_activity
from .utils import ActivityHistoryHelper, ActivityTaskHelper


@Broker.wrap_async_task_decorator
async def project_label_created(user_or_bot: User | Bot, project: Project, label: ProjectLabel):
    helper = ActivityTaskHelper(ProjectActivity)
    activity_history = _get_default_history(helper, project, label)
    activity = helper.record(
        user_or_bot, activity_history, **_get_activity_params(ProjectActivityType.ProjectLabelCreated, project)
    )
    record_project_activity(user_or_bot, activity)


@Broker.wrap_async_task_decorator
async def project_label_updated(
    user_or_bot: User | Bot, project: Project, old_dict: dict[str, Any], label: ProjectLabel
):
    helper = ActivityTaskHelper(ProjectActivity)
    activity_history = {
        **_get_default_history(helper, project, label),
        **ActivityHistoryHelper.create_changes(old_dict, label),
    }
    activity = helper.record(
        user_or_bot, activity_history, **_get_activity_params(ProjectActivityType.ProjectLabelUpdated, project)
    )
    record_project_activity(user_or_bot, activity)


@Broker.wrap_async_task_decorator
async def project_label_deleted(user_or_bot: User | Bot, project: Project, label: ProjectLabel):
    helper = ActivityTaskHelper(ProjectActivity)
    activity_history = _get_default_history(helper, project, label)
    activity = helper.record(
        user_or_bot, activity_history, **_get_activity_params(ProjectActivityType.ProjectLabelDeleted, project)
    )
    record_project_activity(user_or_bot, activity)


def _get_default_history(helper: ActivityTaskHelper, project: Project, label: ProjectLabel):
    history = {
        **helper.create_project_default_history(project),
        "label": ActivityHistoryHelper.create_label_history(label),
    }
    return history


def _get_activity_params(activity_type: ProjectActivityType, project: Project):
    activity_params = {
        "activity_type": activity_type,
        "project_id": project.id,
    }

    return activity_params
