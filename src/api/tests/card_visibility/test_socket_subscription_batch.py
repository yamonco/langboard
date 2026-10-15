"""Real SQL admission stays equivalent while query count stays bounded."""

from types import SimpleNamespace
import pytest
from langboard.routes.auth.forms import SocketSubscriptionAuthorizationItem
from langboard.routes.auth.SocketAuthorization import authorized_subscription_items, is_subscription_authorized
from langboard_shared.core.db import DbSession
from langboard_shared.core.db.DbEngine import DbEngine
from langboard_shared.core.routing import SocketTopic
from langboard_shared.core.types import SafeDateTime
from langboard_shared.domain.models import Card, Project, ProjectAssignedUser, User
from langboard_shared.domain.services.factory.ProjectService import ProjectService
from langboard_shared.Env import Env
from langboard_shared.infrastructure.repositories.factory.ProjectAssignedUserRepository import (
    ProjectAssignedUserRepository,
)
from sqlalchemy import event


pytestmark = pytest.mark.parametrize("current_card", ["sqlite-http", "postgresql-test"], indirect=True)


def service_for(card_service):
    repo = SimpleNamespace(project_assigned_user=ProjectAssignedUserRepository(None, None))
    return SimpleNamespace(card=card_service, project=ProjectService(lambda _: None, lambda _: None, repo))


def query_count(call):
    engine = DbEngine.get_main_engine()
    queries = []
    def observe(*args):
        queries.append(args[2])
    event.listen(engine, "before_cursor_execute", observe)
    try:
        result = call()
    finally:
        event.remove(engine, "before_cursor_execute", observe)
    return result, len(queries)


@pytest.mark.parametrize("topic", [SocketTopic.Dashboard, SocketTopic.Board, SocketTopic.BoardWiki])
def test_project_batch_matches_individual_admission_and_current_membership(current_card, topic):
    user, _, _, card_service = current_card
    service = service_for(card_service)
    projects = []
    with DbSession.atomic() as db:
        for i in range(64):
            project = Project(owner_id=user.id, title=f"Subscription {i}")
            db.insert(project)
            projects.append(project)
            if i % 2 == 0:
                db.insert(ProjectAssignedUser(project_id=project.id, user_id=user.id))
        projects[0].deleted_at = SafeDateTime.now()
        db.update(projects[0])
    items = [SocketSubscriptionAuthorizationItem(topic=topic, topic_id=p.get_uid()) for p in projects]
    expected = [
        {"topic": item.topic.value, "topic_id": item.topic_id} for item in items
        if is_subscription_authorized(service, user, item.topic, item.topic_id)
    ]
    result, queries = query_count(lambda: authorized_subscription_items(service, user, items))
    assert result == expected
    assert len(result) == 31
    assert queries == 1
    assert query_count(lambda: authorized_subscription_items(service, user, items[:1]))[1] == 1
    with DbSession.atomic() as db:
        membership = service.project.repo.project_assigned_user.find_by_user_and_project(user, projects[2])
        db.delete(membership)
    assert items[2].topic_id not in {item["topic_id"] for item in authorized_subscription_items(service, user, items)}
    # Being an administrator or project owner never replaces this topic's assignment requirement.
    user.is_admin = True
    assert authorized_subscription_items(service, user, [items[1]]) == []


@pytest.mark.parametrize("admin", [False, True])
def test_card_batch_matches_policy_with_constant_queries_and_revocation(current_card, monkeypatch, admin):
    user, project, _, card_service = current_card
    monkeypatch.setattr(type(Env), "CARD_INTERNAL_ACCESS_MODE", property(lambda _: "scim"))
    service = service_for(card_service)
    with DbSession.atomic() as db:
        user.is_admin = admin
        db.update(user)
        db.insert(ProjectAssignedUser(project_id=project.id, user_id=user.id))
        other = User(firstname="Other", lastname="Owner", email="other@example.invalid",
                     password="test-only", activated_at=SafeDateTime.now())
        db.insert(other)
        cards = []
        for i in range(64):
            visibility = ["SHARED", "INTERNAL", "PRIVATE", "PRIVATE"][i % 4]
            owner_id = (user.id if i % 4 == 2 else other.id) if visibility == "PRIVATE" else None
            card = Card(project_id=project.id, title=f"Card {i}",
                        visibility=visibility,
                        owner_user_id=owner_id, created_by_user_id=owner_id or user.id)
            db.insert(card)
            cards.append(card)
        cards[0].deleted_at = SafeDateTime.now()
        db.update(cards[0])
    items = [SocketSubscriptionAuthorizationItem(topic=SocketTopic.BoardCard, topic_id=c.get_uid()) for c in cards]
    expected = [
        {"topic": item.topic.value, "topic_id": item.topic_id} for item in items
        if is_subscription_authorized(service, user, item.topic, item.topic_id)
    ]
    result, queries = query_count(lambda: authorized_subscription_items(service, user, items))
    assert result == expected
    assert len(result) == 31  # Shared and own private cards; no internal or another owner's private card.
    assert queries == 3
    assert query_count(lambda: authorized_subscription_items(service, user, items[2:3]))[1] == queries
    with DbSession.atomic() as db:
        membership = service.project.repo.project_assigned_user.find_by_user_and_project(user, project)
        db.delete(membership)
    remaining = authorized_subscription_items(service, user, items)
    assert remaining == (expected if admin else [])
    with DbSession.atomic() as db:
        user.activated_at = None
        db.update(user)
    assert authorized_subscription_items(service, user, items) == []


def test_mixed_batch_keeps_order_duplicates_and_fail_closed_ids(current_card):
    user, project, card, card_service = current_card
    service = service_for(card_service)
    with DbSession.atomic() as db:
        db.insert(ProjectAssignedUser(project_id=project.id, user_id=user.id))
    items = [SocketSubscriptionAuthorizationItem(topic=topic, topic_id=uid) for topic, uid in [
        (SocketTopic.UserPrivate, user.get_uid()), (SocketTopic.BoardCard, card.get_uid()),
        (SocketTopic.Board, project.get_uid()), (SocketTopic.BoardCard, "invalid-code!"),
        (SocketTopic.Dashboard, "invalid-code!"), (SocketTopic.Board, project.get_uid()),
    ]]
    result = authorized_subscription_items(service, user, items)
    assert result == [{"topic": i.topic.value, "topic_id": i.topic_id} for i in (items[0], items[1], items[2], items[5])]
    with DbSession.atomic() as db:
        project.deleted_at = SafeDateTime.now()
        db.update(project)
    assert authorized_subscription_items(service, user, items) == [{"topic": items[0].topic.value, "topic_id": items[0].topic_id}]
