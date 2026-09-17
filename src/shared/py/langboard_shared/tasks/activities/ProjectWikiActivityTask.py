from typing import Any
from ...core.broker import Broker
from ...domain.models import Bot, Project, ProjectWiki, ProjectWikiActivity, User
from ...domain.models.ProjectWikiActivity import ProjectWikiActivityType
from .UserActivityTask import record_wiki_activity
from .utils import ActivityHistoryHelper, ActivityTaskHelper


@Broker.wrap_async_task_decorator
async def project_wiki_created(user_or_bot: User | Bot, project: Project, wiki: ProjectWiki):
    helper = ActivityTaskHelper(ProjectWikiActivity)
    activity_history = _get_default_history(helper, project, wiki)
    activity = helper.record(
        user_or_bot, activity_history, **_get_activity_params(ProjectWikiActivityType.WikiCreated, project, wiki)
    )
    record_wiki_activity(user_or_bot, activity)


@Broker.wrap_async_task_decorator
async def project_wiki_updated(user_or_bot: User | Bot, project: Project, old_dict: dict[str, Any], wiki: ProjectWiki):
    helper = ActivityTaskHelper(ProjectWikiActivity)
    activity_history = {
        **_get_default_history(helper, project, wiki),
        **ActivityHistoryHelper.create_changes(old_dict, wiki),
    }
    activity = helper.record(
        user_or_bot, activity_history, **_get_activity_params(ProjectWikiActivityType.WikiUpdated, project, wiki)
    )
    record_wiki_activity(user_or_bot, activity)


@Broker.wrap_async_task_decorator
async def project_wiki_publicity_changed(
    user_or_bot: User | Bot, project: Project, was_public: bool, wiki: ProjectWiki
):
    helper = ActivityTaskHelper(ProjectWikiActivity)
    activity_history = {
        **_get_default_history(helper, project, wiki),
        "was_public": was_public,
        "is_public": wiki.is_public,
    }
    activity = helper.record(
        user_or_bot,
        activity_history,
        **_get_activity_params(ProjectWikiActivityType.WikiPublicityChanged, project, wiki),
    )
    record_wiki_activity(user_or_bot, activity)


@Broker.wrap_async_task_decorator
async def project_wiki_assignees_updated(
    user: User,
    project: Project,
    wiki: ProjectWiki,
    old_user_ids: list[int],
    new_user_ids: list[int],
):
    helper = ActivityTaskHelper(ProjectWikiActivity)
    removed_users, added_users = helper.get_updated_users(old_user_ids, new_user_ids)
    if not removed_users and not added_users:
        return

    activity_history: dict[str, Any] = {**_get_default_history(helper, project, wiki)}
    if removed_users or added_users:
        activity_history["removed_users"] = removed_users
        activity_history["added_users"] = added_users

    activity = helper.record(
        user,
        activity_history,
        **_get_activity_params(ProjectWikiActivityType.WikiAssigneesUpdated, project, wiki),
    )
    record_wiki_activity(user, activity)


@Broker.wrap_async_task_decorator
async def project_wiki_deleted(user_or_bot: User | Bot, project: Project, wiki: ProjectWiki):
    helper = ActivityTaskHelper(ProjectWikiActivity)
    activity_history = _get_default_history(helper, project, wiki)
    activity = helper.record(
        user_or_bot, activity_history, **_get_activity_params(ProjectWikiActivityType.WikiDeleted, project, wiki)
    )
    record_wiki_activity(user_or_bot, activity)


def _get_default_history(helper: ActivityTaskHelper, project: Project, wiki: ProjectWiki):
    return {
        **helper.create_project_default_history(project),
        "wiki": ActivityHistoryHelper.create_project_wiki_history(wiki),
    }


def _get_activity_params(activity_type: ProjectWikiActivityType, project: Project, wiki: ProjectWiki):
    activity_params = {
        "activity_type": activity_type,
        "project_id": project.id,
        "project_wiki_id": wiki.id,
    }

    return activity_params
