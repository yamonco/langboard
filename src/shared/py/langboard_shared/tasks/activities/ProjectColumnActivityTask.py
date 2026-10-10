from ...core.broker import Broker
from ...domain.models import Bot, Project, ProjectActivity, ProjectColumn, User
from ...domain.models.ProjectActivity import ProjectActivityType
from .UserActivityTask import record_project_activity
from .utils import ActivityHistoryHelper, ActivityTaskHelper


@Broker.wrap_async_task_decorator
async def project_column_created(user_or_bot: User | Bot, project: Project, column: ProjectColumn):
    helper = ActivityTaskHelper(ProjectActivity)
    activity_history = _get_default_history(helper, project, column)
    activity = helper.record(
        user_or_bot, activity_history, **_get_activity_params(ProjectActivityType.ProjectColumnCreated, project, column)
    )
    record_project_activity(user_or_bot, activity)


@Broker.wrap_async_task_decorator
async def project_column_name_changed(user_or_bot: User | Bot, project: Project, old_name: str, column: ProjectColumn):
    helper = ActivityTaskHelper(ProjectActivity)
    activity_history = {
        **_get_default_history(helper, project, column),
        "changes": {"before": {"name": old_name}, "after": {"name": column.name}},
    }
    activity = helper.record(
        user_or_bot,
        activity_history,
        **_get_activity_params(ProjectActivityType.ProjectColumnNameChanged, project, column),
    )
    record_project_activity(user_or_bot, activity)


@Broker.wrap_async_task_decorator
async def project_column_deleted(user_or_bot: User | Bot, project: Project, column: ProjectColumn):
    helper = ActivityTaskHelper(ProjectActivity)
    activity_history = _get_default_history(helper, project, column)
    activity = helper.record(
        user_or_bot, activity_history, **_get_activity_params(ProjectActivityType.ProjectColumnDeleted, project, column)
    )
    record_project_activity(user_or_bot, activity)


def _get_default_history(helper: ActivityTaskHelper, project: Project, column: ProjectColumn):
    history = {
        **helper.create_project_default_history(project),
        "column": ActivityHistoryHelper.create_project_column_history(column),
    }
    return history


def _get_activity_params(activity_type: ProjectActivityType, project: Project, column: ProjectColumn):
    activity_params = {
        "activity_type": activity_type,
        "project_id": project.id,
        "project_column_id": column.id,
    }

    return activity_params
