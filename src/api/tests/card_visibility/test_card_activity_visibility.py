"""Visible activity pages and cursors must not expose hidden card existence."""

from types import SimpleNamespace
from unittest.mock import Mock
import pytest
from langboard.routes.activities import ActivityApi
from langboard.routes.board import BoardApi
from langboard_shared.core.db import DbSession
from langboard_shared.core.db.DbEngine import DbEngine
from langboard_shared.core.routing import ApiException
from langboard_shared.core.security.CollaborationChannel import CollaborationChannel
from langboard_shared.core.types import SafeDateTime
from langboard_shared.domain.models import Card, ProjectActivity, User
from langboard_shared.domain.models.ProjectActivity import ProjectActivityType
from langboard_shared.domain.services.CardVisibilityPolicy import CardVisibilityContext
from langboard_shared.infrastructure.repositories.factory.ActivityRepository import ActivityRepository


@pytest.mark.parametrize("channel", list(CollaborationChannel))
@pytest.mark.parametrize("internal", (True, False))
@pytest.mark.parametrize("current_card", ["sqlite://", "postgresql-test"], indirect=True)
def test_change_feed_filters_before_limit_and_uses_only_visible_cursor(current_card, channel, internal):
    user, project, private, service = current_card
    ProjectActivity.__table__.create(DbEngine.get_main_engine())
    with DbSession.use(readonly=False) as db:
        other = User(firstname="Other", lastname="Owner", email="other-owner@example.invalid", password="test-only")
        db.insert(other)
        shared = Card(project_id=project.id, title="Shared", visibility="SHARED")
        internal_card = Card(project_id=project.id, title="Internal", visibility="INTERNAL")
        foreign = Card(project_id=project.id, title="Foreign vault", visibility="PRIVATE", owner_user_id=other.id, created_by_user_id=other.id)
        deleted = Card(project_id=project.id, title="Deleted", visibility="SHARED", deleted_at=SafeDateTime.now())
        for card in (shared, internal_card, foreign, deleted):
            db.insert(card)
        time = SafeDateTime.now()
        events = []
        # Identical timestamps force cursor tie-breaking by ID.
        for card in (shared, private, internal_card, foreign, deleted, shared):
            event = ProjectActivity(project_id=project.id, card_id=card.id, user_id=user.id,
                                    activity_type=ProjectActivityType.CardUpdated, created_at=time)
            db.insert(event)
            events.append(event)
        # Newer board-level changes must not starve a one-item card page.
        db.insert(ProjectActivity(project_id=project.id, user_id=user.id, activity_type=ProjectActivityType.ProjectUpdated))
    repo = ActivityRepository(None, None)
    service.repo.activity = repo
    context = CardVisibilityContext(channel=channel, active=True, project_member=True, internal_member=internal, actor_user_id=user.id)
    service.resolve_visibility_context = Mock(return_value=(project, context))
    eligible = [events[-1], *([events[2]] if internal else []),
                *([events[1]] if channel in (CollaborationChannel.HumanUI, CollaborationChannel.Mcp) else []), events[0]]
    found = []
    cursor = None
    while True:
        page = service.get_change_feed(project, limit=1, before_activity_uid=cursor, user=user, channel=channel)
        assert len(page["entries"]) == 1
        found.append(page["entries"][0]["activity_uid"])
        if not page["has_more"]:
            assert page["next_cursor"] is None
            break
        cursor = page["next_cursor"]
        assert cursor == found[-1]
    assert found == [event.get_uid() for event in eligible]
    for hidden in (events[3], events[4]):
        assert service.get_change_feed(project, limit=1, before_activity_uid=hidden.get_uid(), user=user, channel=channel) == {
            "entries": [], "has_more": False, "next_cursor": None,
        }
    with DbSession.use(readonly=False) as db:
        shared.visibility = "INTERNAL"
        db.update(shared)
    external = CardVisibilityContext(channel=channel, active=True, project_member=True, internal_member=False, actor_user_id=user.id)
    assert repo.get_card_change_page(project, 1, context=external, before_activity_uid=events[-1].get_uid()) == []
    service.resolve_visibility_context.return_value = None
    assert service.get_change_feed(project, user=user, channel=channel) is None


@pytest.mark.parametrize("name", ("get_card_activities", "get_card_column_history"))
@pytest.mark.parametrize("channel", list(CollaborationChannel))
def test_hidden_direct_card_activity_denied_before_assignee_or_history_lookup(current_card, name, channel):
    user, project, card, card_service = current_card
    with DbSession.use(readonly=False) as db:
        card.owner_user_id = user.id + 1
        card.created_by_user_id = card.owner_user_id
        db.update(card)
    activity = Mock()
    service = SimpleNamespace(card=card_service, activity=activity)
    kwargs = dict(project_uid=project.get_uid(), card_uid=card.get_uid(),
                  request=SimpleNamespace(scope={"collaboration_channel": channel}), user=user, service=service)
    if name == "get_card_activities":
        kwargs["pagination"] = object()
    with pytest.raises(ApiException.NotFound_404):
        getattr(ActivityApi, name)(**kwargs)
    assert activity.mock_calls == []


def test_board_feed_route_forwards_actor_and_server_channel():
    actor = object()
    feed = Mock(return_value={"entries": [], "has_more": False, "next_cursor": None})
    service = SimpleNamespace(project=SimpleNamespace(get_by_id_like=Mock(return_value=object())), card=SimpleNamespace(get_change_feed=feed))
    request = SimpleNamespace(scope={"collaboration_channel": CollaborationChannel.Mcp})
    BoardApi.get_board_change_feed("p", request, 3, "cursor", actor, service)
    feed.assert_called_once_with("p", limit=3, before_activity_uid="cursor", user=actor, channel=CollaborationChannel.Mcp)


@pytest.mark.parametrize("current_card", ["sqlite://", "postgresql-test"], indirect=True)
def test_feed_revalidates_cached_actor_and_current_card_visibility(current_card):
    user, project, card, service = current_card
    ProjectActivity.__table__.create(DbEngine.get_main_engine())
    with DbSession.use(readonly=False) as db:
        event = ProjectActivity(project_id=project.id, card_id=card.id, user_id=user.id,
                                activity_type=ProjectActivityType.CardUpdated)
        db.insert(event)
    service.repo.activity = ActivityRepository(None, None)
    assert len(service.get_change_feed(project, user=user, channel=CollaborationChannel.Mcp)["entries"]) == 1
    assert service.get_change_feed(project, user=user, channel=CollaborationChannel.Api)["entries"] == []
    with DbSession.use(readonly=False) as db:
        other = User(firstname="Other", lastname="Owner", email="other-owner@example.invalid", password="test-only")
        db.insert(other)
        card.owner_user_id = other.id
        card.created_by_user_id = card.owner_user_id
        db.update(card)
    assert service.get_change_feed(project, user=user, channel=CollaborationChannel.Mcp)["entries"] == []
    with DbSession.use(readonly=False) as db:
        user.activated_at = None
        db.update(user)
    assert service.get_change_feed(project, user=user, channel=CollaborationChannel.Mcp) is None
