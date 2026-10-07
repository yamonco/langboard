"""Notification rows and unread counts inherit every referenced card's current ACL."""

import pytest
from langboard_shared.core.db import DbSession
from langboard_shared.core.db.DbEngine import DbEngine
from langboard_shared.core.security.CollaborationChannel import CollaborationChannel
from langboard_shared.domain.models import (
    Card,
    CardComment,
    Checkitem,
    Checklist,
    ProjectInvitation,
    ProjectWiki,
    ProjectWikiAssignedUser,
    UserNotification,
)
from langboard_shared.domain.models.UserNotification import NotificationType
from langboard_shared.infrastructure.repositories.factory.UserNotificationRepository import UserNotificationRepository


@pytest.mark.parametrize("current_card", ["sqlite://", "postgresql-test"], indirect=True)
@pytest.mark.parametrize("channel", list(CollaborationChannel))
def test_notification_scope_precedes_page_and_unread_count(current_card, channel):
    user, project, own, service = current_card
    for model in (CardComment, Checklist, Checkitem, ProjectInvitation, ProjectWiki, ProjectWikiAssignedUser, UserNotification):
        model.__table__.create(DbEngine.get_main_engine())
    repo = UserNotificationRepository(None, None)
    with DbSession.use(readonly=False) as db:
        shared = Card(project_id=project.id, title="shared", visibility="SHARED")
        internal = Card(project_id=project.id, title="internal", visibility="INTERNAL")
        for card in (shared, internal):
            db.insert(card)
        comment = CardComment(card_id=internal.id, user_id=user.id)
        checklist = Checklist(card_id=internal.id, title="hidden")
        db.insert(comment)
        db.insert(checklist)
        item = Checkitem(checklist_id=checklist.id, title="hidden task")
        db.insert(item)
        invitation = ProjectInvitation(project_id=project.id, email=user.email, token="test-only")
        db.insert(invitation)
        invitation_note = UserNotification(receiver_id=user.id, notifier_type="user", notifier_id=user.id,
            notification_type=NotificationType.ProjectInvited,
            record_list=[("project", project.id), ("project_invitation", invitation.id)])
        db.insert(invitation_note)
        visible_ids = []
        for refs in (
            [("project", project.id), ("card", shared.id)],
            [("project", project.id), ("card", own.id)],
            [("project", project.id), ("card", internal.id)],
            [("project", project.id), ("card", shared.id), ("card_comment", comment.id)],
            [("project", project.id), ("checklist", checklist.id)],
            [("project", project.id), ("checkitem", item.id)],
        ):
            notification = UserNotification(receiver_id=user.id, notifier_type="user", notifier_id=user.id,
                notification_type=NotificationType.AssignedToCard, record_list=refs, message_vars={"SECRET": "private text"})
            db.insert(notification)
            if refs[-1][0] == "card" and refs[-1][1] in (shared.id, own.id):
                visible_ids.append(notification.id)
        for malformed in ([], [["unknown", shared.id]]):
            db.insert(UserNotification(receiver_id=user.id, notifier_type="user", notifier_id=user.id,
                notification_type=NotificationType.AssignedToCard, record_list=malformed))
    contexts = service.resolve_work_visibility_contexts(user, channel)
    expected = 2 if channel in (CollaborationChannel.HumanUI, CollaborationChannel.Mcp) else 1
    all_rows, unread = repo.get_scoped_list(user, "all", 1, 20, False, contexts=contexts)
    assert len(all_rows) == unread == expected+1
    assert {row.id for row in all_rows}.issubset([*visible_ids, invitation_note.id])
    rows, same_count = repo.get_scoped_list(user, "all", 1, 1, True, contexts=contexts)
    assert same_count == expected+1 and len(rows) == 2
    with DbSession.use(readonly=False) as db:
        shared.visibility = "INTERNAL"
        db.update(shared)
    rows, unread = repo.get_scoped_list(user, "all", 1, 20, False, contexts=contexts)
    assert len(rows) == unread == expected
    assert repo.get_scoped_list(user, "all", 1, 20, False, contexts={}) == ([invitation_note], 1)


def test_notification_service_uses_current_actor_and_trusted_channel(current_card, monkeypatch):
    from types import SimpleNamespace
    from unittest.mock import Mock
    from langboard_shared.domain.services.factory.NotificationService import NotificationService
    from langboard_shared.helpers import InfraHelper

    user, _, _, card_service = current_card
    query = Mock(return_value=([], 0))
    service = NotificationService(lambda _: card_service, lambda _: None,
        SimpleNamespace(user_notification=SimpleNamespace(get_scoped_list=query)))
    monkeypatch.setattr(InfraHelper, "get_references", lambda *_args, **_kwargs: {})
    assert service.get_api_list(user, "7d", 2, 1, unread_only=True, channel=CollaborationChannel.Mcp) == ([], False, 0)
    assert query.call_args.args[1:] == ("7d", 2, 1, True)
    assert next(iter(query.call_args.kwargs["contexts"].values())).channel == CollaborationChannel.Mcp
    query.reset_mock()
    with DbSession.use(readonly=False) as db:
        user.activated_at = None
        db.update(user)
    assert service.get_api_list(user, "all", channel=CollaborationChannel.Mcp) == ([], False, 0)
    query.assert_not_called()


def test_mysql_notification_reference_query_compiles(monkeypatch):
    from contextlib import contextmanager
    from types import SimpleNamespace
    from sqlalchemy.dialects import mysql

    statements = []
    @contextmanager
    def session(**_kwargs):
        yield SimpleNamespace(exec=lambda query: statements.append(str(query.compile(dialect=mysql.dialect(), compile_kwargs={"literal_binds": True}))) or SimpleNamespace(first=lambda: 0, all=lambda: []))
    monkeypatch.setattr(DbSession, "use", session)
    monkeypatch.setattr(DbEngine, "get_main_engine", lambda: SimpleNamespace(dialect=SimpleNamespace(name="mysql")))
    assert UserNotificationRepository(None, None).get_scoped_list(1, "all", 1, 1, False, contexts={}) == ([], 0)
    assert len(statements) == 2
    assert all("JSON_TABLE(user_notification.record_list, '$[*]' COLUMNS (" in sql for sql in statements)


@pytest.mark.parametrize("visibility,allowed", [("PRIVATE", False), ("INTERNAL", False), ("SHARED", True)])
def test_outbound_creation_checks_current_visibility_before_any_side_effect(current_card, monkeypatch, visibility, allowed):
    from types import SimpleNamespace
    from unittest.mock import Mock
    from langboard_shared.core.publisher import NotificationPublisher
    from langboard_shared.domain.services.factory.NotificationService import NotificationService

    user, project, card, card_service = current_card
    with DbSession.use(readonly=False) as db:
        card.visibility = visibility
        card.owner_user_id = user.id if visibility == "PRIVATE" else None
        db.update(card)
    insert = Mock()
    setting = SimpleNamespace(has_unsubscription=lambda *_args: False)
    service = NotificationService(lambda cls: card_service if cls.__name__ == "CardService" else setting,
        lambda _: None, SimpleNamespace(user_notification=SimpleNamespace(insert=insert)))
    convert = Mock(return_value={})
    publish = Mock()
    schedule = Mock()
    monkeypatch.setattr(service, "convert_to_api_response", convert)
    monkeypatch.setattr(NotificationPublisher, "put_dispather", publish)
    from importlib import import_module
    monkeypatch.setattr(import_module("langboard_shared.domain.services.factory.NotificationService"), "publish_pending_work_events", schedule)
    formats = {"body": "sensitive"}
    result = service._NotificationService__notify(user, user, NotificationType.MentionedInCard,
        [], [project, card], email_formats=formats, allow_self=True)
    assert result is allowed
    assert insert.call_count == convert.call_count == publish.call_count == schedule.call_count == int(allowed)
    assert ("recipient" in formats) is allowed


def test_outbound_uses_live_actor_and_reference_provenance(current_card):
    from types import SimpleNamespace
    from langboard_shared.domain.models import Project, User
    from langboard_shared.domain.services.factory.NotificationService import NotificationService

    user, project, card, card_service = current_card
    for model in (Checklist, Checkitem, ProjectInvitation):
        model.__table__.create(DbEngine.get_main_engine())
    service = NotificationService(lambda _: card_service, lambda _: None, SimpleNamespace())
    with DbSession.use(readonly=False) as db:
        card.visibility = "SHARED"
        card.owner_user_id = None
        db.update(card)
        other = Project(owner_id=user.id, title="Other")
        db.insert(other)
        checklist = Checklist(card_id=card.id, title="Current child")
        db.insert(checklist)
        item = Checkitem(checklist_id=checklist.id, title="Current item")
        db.insert(item)
        invite = ProjectInvitation(project_id=project.id, email=user.email, token="test-only")
        db.insert(invite)
    resolve = service._resolve_notification_recipient
    assert resolve(user, NotificationType.MentionedInCard, [project, card])
    assert resolve(user, NotificationType.ScheduledRule, [project, item])
    assert resolve(user, NotificationType.ProjectInvited, [project, invite])
    assert resolve(user, NotificationType.MentionedInCard, [other, card]) is None
    assert resolve(user, NotificationType.MentionedInCard, []) is None
    cached_user = User.model_validate(user.model_dump())
    with DbSession.use(readonly=False) as db:
        from langboard_shared.core.types import SafeDateTime
        checklist.deleted_at = SafeDateTime.now()
        db.update(checklist)
    assert resolve(user, NotificationType.ScheduledRule, [project, item]) is None
    with DbSession.use(readonly=False) as db:
        user.activated_at = None
        db.update(user)
    assert resolve(cached_user, NotificationType.MentionedInCard, [project, card]) is None
