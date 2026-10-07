"""All scoped activity pages and new-row counts share the same SQL card gate."""

from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import Mock
import pytest
from langboard.mcp_tools import ActivityMcp
from langboard_shared.core.db import DbSession
from langboard_shared.core.db.DbEngine import DbEngine
from langboard_shared.core.schema import TimeBasedPagination
from langboard_shared.core.security.CollaborationChannel import CollaborationChannel
from langboard_shared.core.types import SafeDateTime
from langboard_shared.domain.models import Card, ProjectActivity, ProjectColumn, ProjectWikiActivity, UserActivity
from langboard_shared.domain.models.ProjectActivity import ProjectActivityType
from langboard_shared.domain.services.CardVisibilityPolicy import CardVisibilityContext
from langboard_shared.domain.services.factory.ActivityService import ActivityService
from langboard_shared.infrastructure.repositories.factory.ActivityRepository import ActivityRepository


@pytest.mark.parametrize("channel", list(CollaborationChannel))
@pytest.mark.parametrize("assignee", (True, False))
def test_pages_counts_and_columns_filter_before_limit(current_card, channel, assignee):
    user, project, own, _ = current_card
    engine = DbEngine.get_main_engine()
    for model in (ProjectActivity, ProjectColumn, ProjectWikiActivity, UserActivity):
        model.__table__.create(engine)
    now = SafeDateTime.now()
    with DbSession.use(readonly=False) as db:
        column = ProjectColumn(project_id=project.id, name="Work")
        db.insert(column)
        shared = Card(project_id=project.id, project_column_id=column.id, title="Shared", visibility="SHARED")
        internal = Card(project_id=project.id, project_column_id=column.id, title="Internal", visibility="INTERNAL")
        for card in (shared, internal):
            db.insert(card)
        events = []
        for created in (now - timedelta(seconds=1), now + timedelta(seconds=1)):
            for card in (shared, shared, own, internal):
                activity = ProjectActivity(project_id=project.id, project_column_id=column.id, card_id=card.id,
                    user_id=user.id, created_at=created, activity_type=ProjectActivityType.CardUpdated)
                db.insert(activity)
                db.insert(UserActivity(user_id=user.id, refer_activity_table="project_activity", refer_activity_id=activity.id, created_at=created))
                events.append(activity)
    repo = ActivityRepository(None, None)
    context = CardVisibilityContext(channel=channel, active=True, project_member=True, internal_member=False, actor_user_id=user.id)
    args = dict(context=context, assignee=user if assignee else None)
    expected_count = 3 if channel in (CollaborationChannel.HumanUI, CollaborationChannel.Mcp) else 2
    for extra in ({}, {"column": column}, {"card": shared}):
        expected = 2 if "card" in extra else expected_count
        count = repo.get_scoped_project_activities(project, TimeBasedPagination(limit=1, refer_time=now), only_count=True, **args, **extra)
        assert count == expected
        seen = []
        for page in range(1, expected + 1):
            rows, same_count = repo.get_scoped_project_activities(project, TimeBasedPagination(page=page, limit=1, refer_time=now), **args, **extra)
            assert same_count == count and len(rows) == 1
            seen.extend(rows)
        assert len({row.id for row in seen}) == expected
        rows, _ = repo.get_scoped_project_activities(project, TimeBasedPagination(page=expected + 1, limit=1, refer_time=now), **args, **extra)
        assert rows == []
    with DbSession.use(readonly=False) as db:
        shared.visibility = "INTERNAL"
        db.update(shared)
    count = repo.get_scoped_project_activities(project, TimeBasedPagination(refer_time=now), only_count=True, **args)
    assert count == (1 if expected_count == 3 else 0)


def test_activity_service_rejects_missing_or_revoked_actor_and_hidden_direct_card(current_card):
    user, project, card, card_service = current_card
    repo = SimpleNamespace(activity=Mock())
    service = ActivityService(lambda _: card_service, lambda _: None, repo)
    pagination = TimeBasedPagination()
    assert service.get_api_list_by_project(project, pagination) is None
    assert service.get_api_list_by_project(project, pagination, only_count=True) == 0
    assert service.get_api_list_by_card(project, card, pagination, user=user, channel=CollaborationChannel.Api) is None
    assert repo.activity.mock_calls == []
    with DbSession.use(readonly=False) as db:
        user.activated_at = None
        db.update(user)
    assert service.get_api_list_by_project(project, pagination, user=user, channel=CollaborationChannel.Mcp) is None
    assert repo.activity.mock_calls == []


@pytest.mark.parametrize("callback,extra,method", [
    (ActivityMcp.get_project_activities, {}, "get_api_list_by_project"),
    (ActivityMcp.get_project_column_activities, {"column_uid": "column"}, "get_api_list_by_column"),
    (ActivityMcp.get_card_activities, {"card_uid": "card"}, "get_api_list_by_card"),
])
def test_mcp_activity_routes_forward_fixed_channel(callback, extra, method):
    actor = object()
    command = Mock(return_value=None)
    service = SimpleNamespace(activity=SimpleNamespace(**{method: command}))
    callback(project_uid="p", service=service, user=actor, **extra)
    assert command.call_args.kwargs == {"user": actor, "channel": CollaborationChannel.Mcp}


@pytest.mark.parametrize("kind,extra", [("project", {}), ("column", {"column_uid": "col"}), ("card", {"card_uid": "c"})])
@pytest.mark.parametrize("only_count", (True, False))
def test_rest_activity_queries_forward_server_audience(kind, extra, only_count):
    from langboard.routes.activities import ActivityApi

    actor = SimpleNamespace(is_admin=False)
    command = Mock(return_value=0 if only_count else None)
    resolver = Mock(return_value=(object(), object(), object()))
    service = SimpleNamespace(activity=SimpleNamespace(**{f"get_api_list_by_{kind}": command}),
                              card=SimpleNamespace(resolve_readable_card=resolver))
    pagination = SimpleNamespace(assignee_uid=None, only_count=only_count)
    request = SimpleNamespace(scope={"collaboration_channel": CollaborationChannel.HumanUI})
    callback = {"project": ActivityApi.get_project_activities, "column": ActivityApi.get_project_column_activities, "card": ActivityApi.get_card_activities}[kind]
    callback(project_uid="p", request=request, pagination=pagination, user=actor, service=service, **extra)
    assert command.call_args.kwargs["user"] is actor
    assert command.call_args.kwargs["channel"] == CollaborationChannel.HumanUI
