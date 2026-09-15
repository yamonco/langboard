import json
from datetime import datetime
from typing import Any, Literal, cast, overload
from ....core.db import BaseDbModel
from ....core.domain import BaseDomainService
from ....core.schema import TimeBasedPagination
from ....core.types import SnowflakeID
from ....core.types.ParamTypes import TCardParam, TColumnParam, TProjectParam, TUserOrBotParam, TUserParam, TWikiParam
from ....helpers import InfraHelper
from ...models import (
    Bot,
    Card,
    Project,
    ProjectActivity,
    ProjectColumn,
    ProjectWiki,
    ProjectWikiActivity,
    User,
    UserActivity,
)
from ...models.bases import BaseActivityModel


class ActivityService(BaseDomainService):
    def get_shared_user_activities(
        self,
        viewer: User,
        target_uid: str,
        pagination: TimeBasedPagination,
        activity_uid: str | None = None,
        scope: Literal["project", "wiki"] | None = None,
        offset: int = 0,
        max_chars: int = 4000,
        project_uid: str | None = None,
        since: str | None = None,
        until: str | None = None,
    ) -> dict[str, Any]:
        """Read another person's currently shared workspace history without side effects."""
        if pagination.page < 1 or not 1 <= pagination.limit <= 50 or offset < 0 or not 1 <= max_chars <= 8000:
            raise ValueError("Invalid pagination bounds")
        if activity_uid and scope is None:
            raise ValueError("Activity scope is required for detail")
        start = datetime.fromisoformat(since) if since else None
        end = datetime.fromisoformat(until) if until else None
        if any(value is not None and value.utcoffset() is None for value in (start, end)):
            raise ValueError("Period timestamps must include a timezone")
        if start and end and start >= end:
            raise ValueError("since must be earlier than until")
        target = InfraHelper.get_by_id_like(User, target_uid)
        if not target or target.deleted_at:
            return {"activities": [], "has_more": False}
        rows = self.repo.activity.get_shared_user_activities(
            viewer, target, pagination, activity_uid, scope, project_uid, start, end
        )
        items = []
        for row in rows[: pagination.limit]:
            item = {
                "activity_uid": SnowflakeID(row[0]).to_short_code(),
                "created_at": str(row[1]),
                "activity_type": row[2].value if hasattr(row[2], "value") else row[2],
                "scope": row[3],
                "project": {"uid": SnowflakeID(row[4]).to_short_code(), "title": row[5]},
                "resource": {"uid": SnowflakeID(row[6]).to_short_code(), "title": row[7]} if row[6] else None,
            }
            if activity_uid:
                history = json.dumps(row[8], ensure_ascii=False, sort_keys=True, default=str)
                item.update(
                    {
                        "history_format": "json",
                        "history_fragment": history[offset : offset + max_chars],
                        "offset": offset,
                        "next_offset": offset + max_chars if offset + max_chars < len(history) else None,
                        "total_chars": len(history),
                    }
                )
            items.append(item)
        return {
            "activities": items,
            "has_more": not activity_uid and len(rows) > pagination.limit,
            "refer_time": str(pagination.refer_time),
        }

    @staticmethod
    def name() -> str:
        """DO NOT EDIT THIS METHOD"""
        return "activity"

    @overload
    def get_api_list_by_user(
        self, user: TUserParam | None, pagination: TimeBasedPagination
    ) -> tuple[list[dict[str, Any]], int, User] | None: ...
    @overload
    def get_api_list_by_user(
        self, user: TUserParam | None, pagination: TimeBasedPagination, only_count: Literal[True]
    ) -> int: ...
    def get_api_list_by_user(
        self, user: TUserParam | None, pagination: TimeBasedPagination, only_count: bool = False
    ) -> tuple[list[dict[str, Any]], int, User] | int | None:
        user = InfraHelper.get_by_id_like(User, user)
        if not user:
            if only_count:
                return 0
            return None

        if only_count:
            return self.repo.activity.get_list_by_user(user, pagination, only_count=True)

        activities, count_new_records = self.repo.activity.get_list_by_user(user, pagination, only_count=False)

        api_activties = []
        cached_dict = self.__get_cached_references(activities)
        for activity in activities:
            if not activity.refer_activity_id or not activity.refer_activity_table:
                continue

            if activity.id not in cached_dict:
                continue

            api_activity = {
                **activity.api_response(),
                **cached_dict[activity.id],
            }
            api_activties.append(api_activity)

        return api_activties, count_new_records, user

    @overload
    def get_api_list_by_project(
        self,
        project: TProjectParam | None,
        pagination: TimeBasedPagination,
        only_count: Literal[False] = False,
        assignee: TUserOrBotParam | None = None,
    ) -> tuple[list[dict[str, Any]], int, Project] | None: ...
    @overload
    def get_api_list_by_project(
        self,
        project: TProjectParam | None,
        pagination: TimeBasedPagination,
        only_count: Literal[True],
        assignee: TUserOrBotParam | None = None,
    ) -> int: ...
    def get_api_list_by_project(
        self,
        project: TProjectParam | None,
        pagination: TimeBasedPagination,
        only_count: bool = False,
        assignee: TUserOrBotParam | None = None,
    ) -> tuple[list[dict[str, Any]], int, Project] | int | None:
        project = InfraHelper.get_by_id_like(Project, project)
        if not project:
            if only_count:
                return 0
            return None

        if only_count:
            return self.repo.activity.get_list_by_project(project, pagination, only_count=True, assignee=assignee)

        activities, count_new_records = self.repo.activity.get_list_by_project(
            project, pagination, only_count=False, assignee=assignee
        )

        if assignee:
            api_activities = self.__convert_api_response(cast(Any, activities))
        else:
            api_activities = [activity.api_response() for activity in activities]

        return api_activities, count_new_records, project

    @overload
    def get_api_list_by_column(
        self,
        project: TProjectParam | None,
        column: TColumnParam | None,
        pagination: TimeBasedPagination,
        only_count: Literal[False] = False,
        assignee: TUserOrBotParam | None = None,
    ) -> tuple[list[dict[str, Any]], int, Project, ProjectColumn] | None: ...
    @overload
    def get_api_list_by_column(
        self,
        project: TProjectParam | None,
        column: TColumnParam | None,
        pagination: TimeBasedPagination,
        only_count: Literal[True],
        assignee: TUserOrBotParam | None = None,
    ) -> int: ...
    def get_api_list_by_column(
        self,
        project: TProjectParam | None,
        column: TColumnParam | None,
        pagination: TimeBasedPagination,
        only_count: bool = False,
        assignee: TUserOrBotParam | None = None,
    ) -> tuple[list[dict[str, Any]], int, Project, ProjectColumn] | int | None:
        params = InfraHelper.get_records_with_foreign_by_params((Project, project), (ProjectColumn, column))
        if not params:
            if only_count:
                return 0
            return None
        project, column = params

        if only_count:
            return self.repo.activity.get_list_by_column(
                project, column, pagination, only_count=True, assignee=assignee
            )

        activities, count_new_records = self.repo.activity.get_list_by_column(
            project, column, pagination, only_count=False, assignee=assignee
        )

        if assignee:
            api_activities = self.__convert_api_response(cast(Any, activities))
        else:
            api_activities = [activity.api_response() for activity in activities]

        return api_activities, count_new_records, project, column

    @overload
    def get_api_list_by_card(
        self,
        project: TProjectParam | None,
        card: TCardParam | None,
        pagination: TimeBasedPagination,
        only_count: Literal[False] = False,
        assignee: TUserOrBotParam | None = None,
    ) -> tuple[list[dict[str, Any]], int, Project, Card] | None: ...
    @overload
    def get_api_list_by_card(
        self,
        project: TProjectParam | None,
        card: TCardParam | None,
        pagination: TimeBasedPagination,
        only_count: Literal[True],
        assignee: TUserOrBotParam | None = None,
    ) -> int: ...
    def get_api_list_by_card(
        self,
        project: TProjectParam | None,
        card: TCardParam | None,
        pagination: TimeBasedPagination,
        only_count: bool = False,
        assignee: TUserOrBotParam | None = None,
    ) -> tuple[list[dict[str, Any]], int, Project, Card] | int | None:
        params = InfraHelper.get_records_with_foreign_by_params((Project, project), (Card, card))
        if not params:
            if only_count:
                return 0
            return None
        project, card = params

        if only_count:
            return self.repo.activity.get_list_by_card(project, card, pagination, only_count=True, assignee=assignee)

        activities, count_new_records = self.repo.activity.get_list_by_card(
            project, card, pagination, only_count=False, assignee=assignee
        )

        if assignee:
            api_activities = self.__convert_api_response(cast(Any, activities))
        else:
            api_activities = [activity.api_response() for activity in activities]

        return api_activities, count_new_records, project, card

    @overload
    def get_api_list_by_wiki(
        self,
        project: TProjectParam | None,
        wiki: TWikiParam | None,
        pagination: TimeBasedPagination,
        only_count: Literal[False] = False,
        assignee: TUserOrBotParam | None = None,
    ) -> tuple[list[dict[str, Any]], int, Project, ProjectWiki] | None: ...
    @overload
    def get_api_list_by_wiki(
        self,
        project: TProjectParam | None,
        wiki: TWikiParam | None,
        pagination: TimeBasedPagination,
        only_count: Literal[True],
        assignee: TUserOrBotParam | None = None,
    ) -> int | None: ...
    def get_api_list_by_wiki(
        self,
        project: TProjectParam | None,
        wiki: TWikiParam | None,
        pagination: TimeBasedPagination,
        only_count: bool = False,
        assignee: TUserOrBotParam | None = None,
    ) -> tuple[list[dict[str, Any]], int, Project, ProjectWiki] | int | None:
        params = InfraHelper.get_records_with_foreign_by_params((Project, project), (ProjectWiki, wiki))
        if not params:
            if only_count:
                return 0
            return None
        project, wiki = params

        if only_count:
            return self.repo.activity.get_list_by_wiki(project, wiki, pagination, only_count=True, assignee=assignee)

        activities, count_new_records = self.repo.activity.get_list_by_wiki(
            project, wiki, pagination, only_count=False, assignee=assignee
        )

        if assignee:
            api_activities = self.__convert_api_response(cast(Any, activities))
        else:
            api_activities = [activity.api_response() for activity in activities]

        return api_activities, count_new_records, project, wiki

    def get_user_or_bot(self, user_or_bot_param: TUserOrBotParam) -> User | Bot | None:
        return self.repo.activity.get_user_or_bot(user_or_bot_param)

    def __convert_api_response(self, activities: list[UserActivity]) -> list[dict[str, Any]]:
        api_activties = []
        cached_dict = self.__get_cached_references(activities)
        for activity in activities:
            if not activity.refer_activity_id or not activity.refer_activity_table:
                continue

            if activity.id not in cached_dict:
                continue

            api_activity = {
                **activity.api_response(),
                **cached_dict[activity.id],
            }
            api_activties.append(api_activity)
        return api_activties

    def __get_cached_references(self, activities: list[UserActivity]):
        refer_activities = InfraHelper.get_references(
            [
                (activity.refer_activity_table, activity.refer_activity_id)
                for activity in activities
                if activity.refer_activity_table and activity.refer_activity_id
            ],
            as_type="raw",
        )
        refer_activity_reference_ids: list[tuple[str, int]] = []
        for refer_activity in refer_activities.values():
            if isinstance(refer_activity, ProjectActivity):
                refer_activity_reference_ids.append((Project.__tablename__, refer_activity.project_id))
                if refer_activity.card_id:
                    refer_activity_reference_ids.append((Card.__tablename__, refer_activity.card_id))
            elif isinstance(refer_activity, ProjectWikiActivity):
                refer_activity_reference_ids.append((Project.__tablename__, refer_activity.project_id))
                refer_activity_reference_ids.append((ProjectWiki.__tablename__, refer_activity.project_wiki_id))

        cached_references = InfraHelper.get_references(refer_activity_reference_ids, as_type="raw", with_deleted=True)
        references = {}
        for activity in activities:
            if not activity.refer_activity_id or not activity.refer_activity_table:
                continue

            refer_activitiy_cache_key = f"{activity.refer_activity_table}_{activity.refer_activity_id}"
            if refer_activitiy_cache_key not in refer_activities:
                continue

            refer_activity = cast(BaseActivityModel, refer_activities[refer_activitiy_cache_key])
            activity_references = self.__get_converted_references(cached_references, refer_activity)
            if not activity_references:
                continue

            references[activity.id] = {
                "refer": refer_activity.api_response(),
                "references": activity_references,
            }
        return references

    def __get_converted_references(
        self, cached_references: dict[str, BaseDbModel], activity: BaseActivityModel
    ) -> dict[str, Any] | None:
        activity_references = {}
        if isinstance(activity, (ProjectActivity, ProjectWikiActivity)) and activity.project_id:
            reference = cast(
                Project,
                cached_references.get(f"{Project.__tablename__}_{activity.project_id}"),
            )
            if not reference:
                return None
            activity_references["project"] = reference.api_response()
            if reference.deleted_at:
                activity_references["project"]["is_deleted"] = True

        if isinstance(activity, ProjectActivity) and activity.project_id:
            activity_references["refer_type"] = "project"
            if activity.card_id:
                reference = cast(
                    Card,
                    cached_references.get(f"{Card.__tablename__}_{activity.card_id}"),
                )
                if not reference:
                    return None
                activity_references["card"] = reference.api_response()
                if reference.deleted_at:
                    activity_references["card"]["is_deleted"] = True
        elif isinstance(activity, ProjectWikiActivity) and activity.project_id:
            activity_references["refer_type"] = "project_wiki"
            reference = cast(
                ProjectWiki,
                cached_references.get(f"{ProjectWiki.__tablename__}_{activity.project_wiki_id}"),
            )
            if not reference:
                return None
            activity_references["project_wiki"] = reference.api_response()
            if reference.deleted_at:
                activity_references["project_wiki"]["is_deleted"] = True

        if not activity_references:
            return None
        return activity_references
