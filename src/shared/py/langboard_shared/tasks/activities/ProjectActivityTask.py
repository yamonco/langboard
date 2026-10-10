from typing import Any
from ...core.broker import Broker
from ...domain.models import Bot, Project, ProjectActivity, User
from ...domain.models.ProjectActivity import ProjectActivityType
from .UserActivityTask import record_project_activity
from .utils import ActivityHistoryHelper, ActivityTaskHelper


@Broker.wrap_async_task_decorator
async def project_created(user: User, project: Project):
    helper = ActivityTaskHelper(ProjectActivity)
    activity_history = helper.create_project_default_history(project)
    activity = helper.record(
        user, activity_history, **_get_activity_params(ProjectActivityType.ProjectCreated, project)
    )
    record_project_activity(user, activity)


@Broker.wrap_async_task_decorator
async def project_updated(user_or_bot: User | Bot, old_dict: dict[str, Any], project: Project):
    helper = ActivityTaskHelper(ProjectActivity)
    activity_history = {
        **helper.create_project_default_history(project),
        **ActivityHistoryHelper.create_changes(old_dict, project),
    }
    activity = helper.record(
        user_or_bot, activity_history, **_get_activity_params(ProjectActivityType.ProjectUpdated, project)
    )
    record_project_activity(user_or_bot, activity)


@Broker.wrap_async_task_decorator
async def project_assigned_users_updated(
    user: User, project: Project, old_user_ids: list[int], new_user_ids: list[int]
):
    helper = ActivityTaskHelper(ProjectActivity)
    removed_users, added_users = helper.get_updated_users(old_user_ids, new_user_ids)
    if not removed_users and not added_users:
        return

    activity_history = {
        **helper.create_project_default_history(project),
        "removed_users": removed_users,
        "added_users": added_users,
    }
    activity = helper.record(
        user, activity_history, **_get_activity_params(ProjectActivityType.ProjectAssignedUsersUpdated, project)
    )
    record_project_activity(user, activity)


@Broker.wrap_async_task_decorator
async def project_email_notification_policy_updated(
    user: User,
    project: Project,
    added_external_emails: list[str],
    removed_external_emails: list[str],
):
    """Record exact edge recipient changes in the native project activity lineage."""

    helper = ActivityTaskHelper(ProjectActivity)
    activity_history = {
        **helper.create_project_default_history(project),
        "added_external_emails": added_external_emails,
        "removed_external_emails": removed_external_emails,
    }
    activity = helper.record(
        user,
        activity_history,
        **_get_activity_params(ProjectActivityType.ProjectEmailNotificationPolicyUpdated, project),
    )
    record_project_activity(user, activity)


@Broker.wrap_async_task_decorator
async def project_invited_user_accepted(user: User, project: Project):
    helper = ActivityTaskHelper(ProjectActivity)
    activity_history = helper.create_project_default_history(project)
    activity = helper.record(
        user,
        activity_history,
        **_get_activity_params(ProjectActivityType.ProjectInvitedUserAccepted, project),
    )
    record_project_activity(user, activity)


@Broker.wrap_async_task_decorator
async def project_deleted(user: User, project: Project):
    helper = ActivityTaskHelper(ProjectActivity)
    activity_history = helper.create_project_default_history(project)
    activity = helper.record(
        user, activity_history, **_get_activity_params(ProjectActivityType.ProjectDeleted, project)
    )
    record_project_activity(user, activity)


def _get_activity_params(activity_type: ProjectActivityType, project: Project):
    activity_params = {
        "activity_type": activity_type,
        "project_id": project.id,
    }

    return activity_params
