"""Project-authorized notification pagination tests."""

from sqlalchemy import create_engine
from ....core.db import DbSession
from ....core.db.DbEngine import DbEngine
from ....domain.models import Project, ProjectAssignedUser, UserNotification
from ....domain.models.UserNotification import NotificationType
from .UserNotificationRepository import UserNotificationRepository


def test_authorization_filters_notifications_before_page_limit(monkeypatch) -> None:
    """A revoked-project row cannot hide an older authorized notification."""

    engine = create_engine("sqlite://")
    for model in (Project, ProjectAssignedUser, UserNotification):
        model.__table__.create(engine)
    monkeypatch.setattr(DbEngine, "get_main_engine", lambda: engine)
    monkeypatch.setattr(DbEngine, "get_readonly_engine", lambda: engine)
    try:
        with DbSession.use(readonly=False) as db:
            allowed = Project(owner_id=1, title="Allowed")
            revoked = Project(owner_id=2, title="Revoked")
            db.insert(allowed)
            db.insert(revoked)
            db.insert(ProjectAssignedUser(project_id=allowed.id, user_id=1))
            db.insert(
                UserNotification(
                    notifier_type="user",
                    notifier_id=2,
                    receiver_id=1,
                    notification_type=NotificationType.MentionedInCard,
                    record_list=[("project", allowed.id)],
                )
            )
            db.insert(
                UserNotification(
                    notifier_type="user",
                    notifier_id=2,
                    receiver_id=1,
                    notification_type=NotificationType.MentionedInCard,
                    record_list=[("project", revoked.id)],
                )
            )

        repository = UserNotificationRepository(lambda _: None, lambda _: None)
        records = repository.get_list(1, "all", page=1, limit=1, authorized_projects_only=True)

        assert len(records) == 1
        assert records[0].record_list == [["project", allowed.id]]
    finally:
        engine.dispose()


def test_project_invitation_remains_visible_before_membership(monkeypatch) -> None:
    """An invitation is readable before the invited user has project membership."""

    engine = create_engine("sqlite://")
    for model in (Project, ProjectAssignedUser, UserNotification):
        model.__table__.create(engine)
    monkeypatch.setattr(DbEngine, "get_main_engine", lambda: engine)
    monkeypatch.setattr(DbEngine, "get_readonly_engine", lambda: engine)
    try:
        with DbSession.use(readonly=False) as db:
            project = Project(owner_id=2, title="Invited")
            db.insert(project)
            db.insert(
                UserNotification(
                    notifier_type="user",
                    notifier_id=2,
                    receiver_id=1,
                    notification_type=NotificationType.ProjectInvited,
                    record_list=[("project", project.id)],
                )
            )

        repository = UserNotificationRepository(lambda _: None, lambda _: None)
        records = repository.get_list(1, "all", page=1, limit=1, authorized_projects_only=True)

        assert len(records) == 1
        assert records[0].notification_type == NotificationType.ProjectInvited
    finally:
        engine.dispose()
