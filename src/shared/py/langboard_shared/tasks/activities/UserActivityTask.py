from ...core.broker import Broker
from ...domain.models import Bot, Project, ProjectActivity, ProjectWikiActivity, User, UserActivity
from ...domain.models.bases import BaseActivityModel
from ...domain.models.UserActivity import UserActivityType
from .utils import ActivityHistoryHelper, ActivityTaskHelper


@Broker.wrap_async_task_decorator
async def activated(user: User):
    helper = ActivityTaskHelper(UserActivity)
    activity_history = {
        "activated_at": ActivityHistoryHelper.convert_to_python(user.activated_at),
    }
    helper.record(user, activity_history, activity_type=UserActivityType.Activated)


@Broker.wrap_async_task_decorator
async def declined_project_invitation(user: User, project: Project):
    helper = ActivityTaskHelper(UserActivity)
    activity_history = {
        "project_title": project.title,
    }
    helper.record(user, activity_history, activity_type=UserActivityType.DeclinedProjectInvitation)


def record_project_activity(user_or_bot: User | Bot, activity: ProjectActivity):
    helper = ActivityTaskHelper(UserActivity)
    helper.record(user_or_bot, {}, **_refer_activity(activity))
    from ..notifications.ProjectEmailNotificationTask import fanout_project_activity_email

    fanout_project_activity_email(activity.__tablename__, activity.id)


def record_wiki_activity(user_or_bot: User | Bot, activity: ProjectWikiActivity):
    helper = ActivityTaskHelper(UserActivity)
    helper.record(user_or_bot, {}, **_refer_activity(activity))
    from ..notifications.ProjectEmailNotificationTask import fanout_project_activity_email

    fanout_project_activity_email(activity.__tablename__, activity.id)


def _refer_activity(activity: BaseActivityModel):
    return {
        "refer_activity_table": activity.__tablename__,
        "refer_activity_id": activity.id,
    }
