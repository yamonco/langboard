from datetime import datetime
from typing import Literal, TypeAlias, TypeVar, overload, override
from sqlalchemy import String, cast, literal, or_, select, union_all
from ....core.db import DbSession, SqlBuilder
from ....core.db.queries.Select import SelectOfScalar
from ....core.domain import BaseRepository
from ....core.schema import TimeBasedPagination
from ....core.types import SafeDateTime, SnowflakeID
from ....core.types.ParamTypes import TCardParam, TColumnParam, TProjectParam, TUserOrBotParam, TUserParam, TWikiParam
from ....domain.models import (
    Bot,
    Card,
    Project,
    ProjectActivity,
    ProjectAssignedUser,
    ProjectRole,
    ProjectWiki,
    ProjectWikiActivity,
    ProjectWikiAssignedUser,
    User,
    UserActivity,
)
from ....domain.models.bases import BaseActivityModel
from ....helpers import InfraHelper


_TActivityModel = TypeVar("_TActivityModel", bound=BaseActivityModel)
_TScopedActivityModel = TypeVar("_TScopedActivityModel", ProjectActivity, ProjectWikiActivity)
_TSelectParam = TypeVar("_TSelectParam")
_TActivityScope = Literal["project", "project_column", "card", "project_wiki"]
_TUserOrBotActivityParam: TypeAlias = User | Bot | SnowflakeID | int | str


class ActivityRepository(BaseRepository[BaseActivityModel]):
    def get_shared_user_activities(
        self,
        viewer: User,
        target: User,
        pagination: TimeBasedPagination,
        activity_uid: str | None = None,
        scope: Literal["project", "wiki"] | None = None,
        project_uid: str | None = None,
        since: datetime | None = None,
        until: datetime | None = None,
    ) -> list:
        """Authorize before paging; list queries never select editing history.

        Even administrators must belong to the same board as the target here.
        This is a collaboration history endpoint, not an administrator audit feed.
        """
        queries = []
        for kind, model in (("project", ProjectActivity), ("wiki", ProjectWikiActivity)):
            if scope and kind != scope:
                continue
            columns = [
                model.column("id"),
                model.column("created_at"),
                cast(model.column("activity_type"), String).label("activity_type"),
                literal(kind).label("scope"),
                Project.column("id").label("project_id"),
                Project.column("title").label("project_title"),
            ]
            if kind == "project":
                columns.extend([Card.column("id").label("resource_id"), Card.column("title").label("resource_title")])
            else:
                columns.extend(
                    [
                        ProjectWiki.column("id").label("resource_id"),
                        ProjectWiki.column("title").label("resource_title"),
                    ]
                )
            if activity_uid:
                columns.append(model.column("activity_history"))
            query = select(*columns).join(Project, Project.column("id") == model.column("project_id"))
            if kind == "project":
                query = query.outerjoin(Card, Card.column("id") == ProjectActivity.column("card_id"))
            else:
                query = query.join(
                    ProjectWiki, ProjectWiki.column("id") == ProjectWikiActivity.column("project_wiki_id")
                )
                query = query.where(ProjectWiki.column("deleted_at").is_(None))
            query = query.where(
                model.column("user_id") == target.id,
                Project.column("deleted_at").is_(None),
                model.column("created_at") <= pagination.refer_time,
            )
            if project_uid:
                query = query.where(Project.column("id") == InfraHelper.convert_id(project_uid))
            if since:
                query = query.where(model.column("created_at") >= since)
            if until:
                query = query.where(model.column("created_at") < until)
            for person in (viewer, target):
                membership = (
                    select(ProjectAssignedUser.column("id"))
                    .where(
                        ProjectAssignedUser.column("project_id") == Project.column("id"),
                        ProjectAssignedUser.column("user_id") == person.id,
                    )
                    .exists()
                )
                query = query.where(membership)
                if not person.is_admin:
                    actions = literal(",") + cast(ProjectRole.column("actions"), String) + literal(",")
                    readable = (
                        select(ProjectRole.column("id"))
                        .where(
                            ProjectRole.column("project_id") == Project.column("id"),
                            ProjectRole.column("user_id") == person.id,
                            or_(actions.contains(",read,"), actions.contains(",*,")),
                        )
                        .exists()
                    )
                    query = query.where(or_(Project.column("owner_id") == person.id, readable))
                if kind == "wiki" and not person.is_admin:
                    assigned = (
                        select(ProjectWikiAssignedUser.column("id"))
                        .where(
                            ProjectWikiAssignedUser.column("project_wiki_id") == ProjectWiki.column("id"),
                            ProjectWikiAssignedUser.column("user_id") == person.id,
                        )
                        .exists()
                    )
                    query = query.where(
                        or_(
                            ProjectWiki.column("is_public").is_(True),
                            Project.column("owner_id") == person.id,
                            assigned,
                        )
                    )
            if activity_uid:
                query = query.where(model.column("id") == InfraHelper.convert_id(activity_uid))
            queries.append(query)
        combined = union_all(*queries).subquery()
        statement = select(combined).order_by(combined.c.created_at.desc(), combined.c.id.desc())
        if not activity_uid:
            statement = statement.offset((pagination.page - 1) * pagination.limit).limit(pagination.limit + 1)
        else:
            statement = statement.limit(1)
        with DbSession.use(readonly=True) as db:
            return list(db.exec(statement).all())

    @staticmethod
    @override
    def name() -> str:
        return "activity"

    @overload
    def get_list_by_user(
        self, user: TUserParam, pagination: TimeBasedPagination, only_count: Literal[False] = False
    ) -> tuple[list[UserActivity], int]: ...
    @overload
    def get_list_by_user(self, user: TUserParam, pagination: TimeBasedPagination, only_count: Literal[True]) -> int: ...
    def get_list_by_user(
        self, user: TUserParam, pagination: TimeBasedPagination, only_count: bool = False
    ) -> tuple[list[UserActivity], int] | int:
        user_id = InfraHelper.convert_id(user)

        if only_count:
            return self.__count_new_records(UserActivity, pagination.refer_time, user_id=user_id)

        result = self.__get_list(UserActivity, pagination, user_id=user_id)
        return result

    @overload
    def get_list_by_project(
        self,
        project: TProjectParam,
        pagination: TimeBasedPagination,
        only_count: Literal[False] = False,
        *,
        assignee: _TUserOrBotActivityParam,
    ) -> tuple[list[UserActivity], int]: ...
    @overload
    def get_list_by_project(
        self,
        project: TProjectParam,
        pagination: TimeBasedPagination,
        only_count: Literal[False] = False,
        *,
        assignee: None = None,
    ) -> tuple[list[ProjectActivity] | list[UserActivity], int]: ...
    @overload
    def get_list_by_project(
        self,
        project: TProjectParam,
        pagination: TimeBasedPagination,
        only_count: Literal[True],
        *,
        assignee: TUserOrBotParam | None = None,
    ) -> int: ...
    def get_list_by_project(
        self,
        project: TProjectParam,
        pagination: TimeBasedPagination,
        only_count: bool = False,
        *,
        assignee: TUserOrBotParam | None = None,
    ) -> tuple[list[ProjectActivity] | list[UserActivity], int] | int:
        project_id = InfraHelper.convert_id(project)

        activity_class, list_query, outdated_query, where_clauses = self.__create_refer_activity_queries(
            ProjectActivity, "project", assignee=assignee, project=project_id
        )
        if not where_clauses:
            where_clauses = {"project_id": project_id}

        if only_count:
            return self.__count_activity_result(activity_class, pagination.refer_time, outdated_query, **where_clauses)

        result = self.__get_project_activity_result(
            activity_class, pagination, list_query, outdated_query, **where_clauses
        )
        return result

    @overload
    def get_list_by_column(
        self,
        project: TProjectParam,
        column: TColumnParam,
        pagination: TimeBasedPagination,
        only_count: Literal[False] = False,
        *,
        assignee: _TUserOrBotActivityParam,
    ) -> tuple[list[UserActivity], int]: ...
    @overload
    def get_list_by_column(
        self,
        project: TProjectParam,
        column: TColumnParam,
        pagination: TimeBasedPagination,
        only_count: Literal[False] = False,
        *,
        assignee: None = None,
    ) -> tuple[list[ProjectActivity] | list[UserActivity], int]: ...
    @overload
    def get_list_by_column(
        self,
        project: TProjectParam,
        column: TColumnParam,
        pagination: TimeBasedPagination,
        only_count: Literal[True],
        *,
        assignee: TUserOrBotParam | None = None,
    ) -> int: ...
    def get_list_by_column(
        self,
        project: TProjectParam,
        column: TColumnParam,
        pagination: TimeBasedPagination,
        only_count: bool = False,
        *,
        assignee: TUserOrBotParam | None = None,
    ) -> tuple[list[ProjectActivity] | list[UserActivity], int] | int:
        project_id = InfraHelper.convert_id(project)
        column_id = InfraHelper.convert_id(column)

        activity_class, list_query, outdated_query, where_clauses = self.__create_refer_activity_queries(
            ProjectActivity, "project", assignee=assignee, project=project_id, project_column=column_id
        )
        if not where_clauses:
            where_clauses = {"project_id": project_id, "column_id": column_id}

        if only_count:
            return self.__count_activity_result(activity_class, pagination.refer_time, outdated_query, **where_clauses)

        result = self.__get_project_activity_result(
            activity_class, pagination, list_query, outdated_query, **where_clauses
        )
        return result

    @overload
    def get_list_by_card(
        self,
        project: TProjectParam,
        card: TCardParam,
        pagination: TimeBasedPagination,
        only_count: Literal[False] = False,
        *,
        assignee: _TUserOrBotActivityParam,
    ) -> tuple[list[UserActivity], int]: ...
    @overload
    def get_list_by_card(
        self,
        project: TProjectParam,
        card: TCardParam,
        pagination: TimeBasedPagination,
        only_count: Literal[False] = False,
        *,
        assignee: None = None,
    ) -> tuple[list[ProjectActivity] | list[UserActivity], int]: ...
    @overload
    def get_list_by_card(
        self,
        project: TProjectParam,
        card: TCardParam,
        pagination: TimeBasedPagination,
        only_count: Literal[True],
        *,
        assignee: TUserOrBotParam | None = None,
    ) -> int: ...
    def get_list_by_card(
        self,
        project: TProjectParam,
        card: TCardParam,
        pagination: TimeBasedPagination,
        only_count: bool = False,
        *,
        assignee: TUserOrBotParam | None = None,
    ) -> tuple[list[ProjectActivity] | list[UserActivity], int] | int:
        project_id = InfraHelper.convert_id(project)
        card_id = InfraHelper.convert_id(card)

        activity_class, list_query, outdated_query, where_clauses = self.__create_refer_activity_queries(
            ProjectActivity, "project", assignee=assignee, project=project_id, card=card_id
        )
        if not where_clauses:
            where_clauses = {"project_id": project_id, "card_id": card_id}

        if only_count:
            return self.__count_activity_result(activity_class, pagination.refer_time, outdated_query, **where_clauses)

        result = self.__get_project_activity_result(
            activity_class, pagination, list_query, outdated_query, **where_clauses
        )
        return result

    @overload
    def get_list_by_wiki(
        self,
        project: TProjectParam,
        wiki: TWikiParam,
        pagination: TimeBasedPagination,
        only_count: Literal[False] = False,
        *,
        assignee: _TUserOrBotActivityParam,
    ) -> tuple[list[UserActivity], int]: ...
    @overload
    def get_list_by_wiki(
        self,
        project: TProjectParam,
        wiki: TWikiParam,
        pagination: TimeBasedPagination,
        only_count: Literal[False] = False,
        *,
        assignee: None = None,
    ) -> tuple[list[ProjectWikiActivity] | list[UserActivity], int]: ...
    @overload
    def get_list_by_wiki(
        self,
        project: TProjectParam,
        wiki: TWikiParam,
        pagination: TimeBasedPagination,
        only_count: Literal[True],
        *,
        assignee: TUserOrBotParam | None = None,
    ) -> int: ...
    def get_list_by_wiki(
        self,
        project: TProjectParam,
        wiki: TWikiParam,
        pagination: TimeBasedPagination,
        only_count: bool = False,
        *,
        assignee: TUserOrBotParam | None = None,
    ) -> tuple[list[ProjectWikiActivity] | list[UserActivity], int] | int:
        project_id = InfraHelper.convert_id(project)
        wiki_id = InfraHelper.convert_id(wiki)

        activity_class, list_query, outdated_query, where_clauses = self.__create_refer_activity_queries(
            ProjectWikiActivity, "project", assignee=assignee, project=project_id, project_wiki=wiki_id
        )
        if not where_clauses:
            where_clauses = {"project_id": project_id, "project_wiki_id": wiki_id}

        if only_count:
            return self.__count_activity_result(activity_class, pagination.refer_time, outdated_query, **where_clauses)

        result = self.__get_wiki_activity_result(
            activity_class, pagination, list_query, outdated_query, **where_clauses
        )
        return result

    def get_user_or_bot(self, user_or_bot_param: TUserOrBotParam) -> User | Bot | None:
        if isinstance(user_or_bot_param, (User, Bot)):
            return user_or_bot_param

        user_or_bot_id = InfraHelper.convert_id(user_or_bot_param)
        user = InfraHelper.get_by(User, "id", user_or_bot_id)
        if user:
            return user

        return InfraHelper.get_by(Bot, "id", user_or_bot_id)

    def __get_list(
        self,
        activity_class: type[_TActivityModel],
        pagination: TimeBasedPagination,
        list_query: SelectOfScalar[_TActivityModel] | None = None,
        outdated_query: SelectOfScalar[int] | None = None,
        **where_clauses: SnowflakeID,
    ) -> tuple[list[_TActivityModel], int]:
        if list_query is None:
            list_query = SqlBuilder.select.table(activity_class)
        list_query = self.__make_query(list_query, activity_class, **where_clauses)
        list_query = list_query.where(activity_class.column("created_at") <= pagination.refer_time)
        list_query = InfraHelper.paginate(list_query, pagination.page, pagination.limit)
        records = []
        with DbSession.use(readonly=True) as db:
            result = db.exec(list_query)
            records = result.all()

        count_new_records = self.__count_new_records(
            activity_class, pagination.refer_time, outdated_query, **where_clauses
        )

        return records, count_new_records

    def __count_new_records(
        self,
        activity_class: type[_TActivityModel],
        refer_time: SafeDateTime,
        outdated_query: SelectOfScalar[int] | None = None,
        **where_clauses: SnowflakeID,
    ) -> int:
        if outdated_query is None:
            outdated_query = SqlBuilder.select.count(activity_class, activity_class.column("id", SnowflakeID))
        outdated_query = self.__make_query(outdated_query, activity_class, **where_clauses)
        outdated_query = outdated_query.where(activity_class.column("created_at", SafeDateTime) > refer_time)
        record = 0
        with DbSession.use(readonly=True) as db:
            result = db.exec(outdated_query)
            record = result.first() or 0
        return record

    def __make_query(
        self,
        query: SelectOfScalar[_TSelectParam],
        activity_class: type[_TActivityModel],
        **where_clauses: SnowflakeID,
    ) -> SelectOfScalar[_TSelectParam]:
        query = query.order_by(activity_class.column("created_at", SafeDateTime).desc()).group_by(
            activity_class.column("id", SnowflakeID), activity_class.column("created_at", SafeDateTime)
        )
        query = InfraHelper.where_recursive(query, activity_class, **where_clauses)
        return query

    def __get_project_activity_result(
        self,
        activity_class: type[ProjectActivity] | type[UserActivity],
        pagination: TimeBasedPagination,
        list_query: SelectOfScalar[UserActivity] | None,
        outdated_query: SelectOfScalar[int] | None,
        **where_clauses: SnowflakeID,
    ) -> tuple[list[ProjectActivity] | list[UserActivity], int]:
        if activity_class is UserActivity:
            return self.__get_list(UserActivity, pagination, list_query, outdated_query, **where_clauses)

        return self.__get_list(ProjectActivity, pagination, None, None, **where_clauses)

    def __get_wiki_activity_result(
        self,
        activity_class: type[ProjectWikiActivity] | type[UserActivity],
        pagination: TimeBasedPagination,
        list_query: SelectOfScalar[UserActivity] | None,
        outdated_query: SelectOfScalar[int] | None,
        **where_clauses: SnowflakeID,
    ) -> tuple[list[ProjectWikiActivity] | list[UserActivity], int]:
        if activity_class is UserActivity:
            return self.__get_list(UserActivity, pagination, list_query, outdated_query, **where_clauses)

        return self.__get_list(ProjectWikiActivity, pagination, None, None, **where_clauses)

    def __count_activity_result(
        self,
        activity_class: type[_TScopedActivityModel] | type[UserActivity],
        refer_time: SafeDateTime,
        outdated_query: SelectOfScalar[int] | None,
        **where_clauses: SnowflakeID,
    ) -> int:
        if activity_class is UserActivity:
            return self.__count_new_records(UserActivity, refer_time, outdated_query, **where_clauses)

        return self.__count_new_records(activity_class, refer_time, None, **where_clauses)

    def __create_refer_activity_queries(
        self,
        activity_class: type[_TScopedActivityModel],
        scope: _TActivityScope,
        *,
        assignee: TUserOrBotParam | None = None,
        **kwargs: SnowflakeID,
    ) -> tuple[
        type[_TScopedActivityModel] | type[UserActivity],
        SelectOfScalar[UserActivity] | None,
        SelectOfScalar[int] | None,
        dict[str, SnowflakeID],
    ]:
        if not assignee:
            return activity_class, None, None, {}

        assignee = self.get_user_or_bot(assignee)
        if not assignee:
            return activity_class, None, None, {}

        list_query = self.__refer(SqlBuilder.select.table(UserActivity), scope, **kwargs)
        outdated_query = self.__refer(
            SqlBuilder.select.count(UserActivity, UserActivity.column("id", SnowflakeID)), scope, **kwargs
        )
        where_clauses: dict[str, SnowflakeID] = {}

        if isinstance(assignee, User):
            where_clauses["user_id"] = assignee.id
        else:
            where_clauses["bot_id"] = assignee.id

        return UserActivity, list_query, outdated_query, where_clauses

    @overload
    def __refer(
        self, query: SelectOfScalar[_TActivityModel], scope: _TActivityScope, **kwargs: SnowflakeID
    ) -> SelectOfScalar[_TActivityModel]: ...
    @overload
    def __refer(
        self, query: SelectOfScalar[int], scope: _TActivityScope, **kwargs: SnowflakeID
    ) -> SelectOfScalar[int]: ...
    def __refer(
        self,
        query: SelectOfScalar[_TActivityModel] | SelectOfScalar[int],
        scope: _TActivityScope,
        **kwargs: SnowflakeID,
    ) -> SelectOfScalar[_TActivityModel] | SelectOfScalar[int]:
        tables = []
        if scope in {"project", "project_wiki"}:
            query = query.outerjoin(
                ProjectActivity,
                (UserActivity.column("refer_activity_table") == ProjectActivity.__tablename__)
                & (ProjectActivity.column("id") == UserActivity.column("refer_activity_id")),
            ).outerjoin(
                ProjectWikiActivity,
                (UserActivity.column("refer_activity_table") == ProjectWikiActivity.__tablename__)
                & (ProjectWikiActivity.column("id") == UserActivity.column("refer_activity_id")),
            )
            tables = [ProjectActivity, ProjectWikiActivity]
        elif scope in {"project_column", "card"}:
            query = query.outerjoin(
                ProjectActivity,
                (UserActivity.column("refer_activity_table") == ProjectActivity.__tablename__)
                & (ProjectActivity.column("id") == UserActivity.column("refer_activity_id")),
            )
            tables = [ProjectActivity]

        for key, value in kwargs.items():
            value = InfraHelper.convert_id(value)
            key = f"{key}_id"

            or_clauses = None
            for table in tables:
                if key not in table.model_fields:
                    continue

                if or_clauses is None:
                    or_clauses = table.column(key) == value
                else:
                    or_clauses |= table.column(key) == value

            if or_clauses is not None:
                query = query.where(or_clauses)

        return query
