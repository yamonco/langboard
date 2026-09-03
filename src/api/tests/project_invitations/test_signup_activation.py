from types import SimpleNamespace
from unittest.mock import Mock, patch
from langboard_shared.core.types import SnowflakeID
from langboard_shared.domain.models import Project, ProjectInvitation, User
from langboard_shared.domain.services.factory.NotificationService import NotificationService
from langboard_shared.domain.services.factory.ProjectInvitationService import ProjectInvitationService
from langboard_shared.domain.services.factory.ProjectService import ProjectService
from langboard_shared.domain.services.factory.UserService import UserService


def test_account_activation_processes_pending_invitations() -> None:
    user = User.model_construct(id=SnowflakeID(1), email="invitee@example.com", activated_at=None)
    calls: list[str] = []
    invitation_service = SimpleNamespace(update_by_signed_up=lambda activated_user: calls.append(activated_user.email))
    repository = SimpleNamespace(user=SimpleNamespace(update=Mock()))
    service = UserService(lambda _: None, lambda _: invitation_service, repository)

    service.activate(user)

    repository.user.update.assert_called_once_with(user)
    assert user.activated_at is not None
    assert calls == [user.email]


def test_signup_notification_keeps_invitation_and_uses_project_owner() -> None:
    invitee = User.model_construct(id=SnowflakeID(1), email="invitee@example.com")
    owner = User.model_construct(id=SnowflakeID(2), email="owner@example.com")
    project = Project.model_construct(id=SnowflakeID(3), owner_id=owner.id, title="Invited project")
    invitation = ProjectInvitation.model_construct(
        id=SnowflakeID(4), project_id=project.id, email=invitee.email, token="pending-token"
    )
    invitation_repository = SimpleNamespace(
        get_all_with_projects_by_email=Mock(return_value=[(invitation, project)]),
        get_all_by_project_with_user=Mock(return_value=[(invitation, invitee)]),
        delete=Mock(),
    )
    user_notification_repository = SimpleNamespace(get_project_invitation_notification=Mock(return_value=None))
    repository = SimpleNamespace(
        project_invitation=invitation_repository,
        user_notification=user_notification_repository,
    )
    notification_service = SimpleNamespace(
        create_record_list=lambda records: [(type(record).__tablename__, record.id) for record in records],
        notify_project_invited=Mock(),
    )
    project_service = SimpleNamespace(get_api_assigned_user_list=Mock(return_value=[]))

    def get_service(service_type: type) -> object:
        if service_type is NotificationService:
            return notification_service
        if service_type is ProjectService:
            return project_service
        raise AssertionError(f"Unexpected service: {service_type}")

    service = ProjectInvitationService(get_service, lambda _: None, repository)

    with (
        patch(
            "langboard_shared.domain.services.factory.ProjectInvitationService.InfraHelper.get_by_id_like",
            return_value=owner,
        ),
        patch(
            "langboard_shared.domain.services.factory.ProjectInvitationService.ProjectPublisher.assigned_users_updated"
        ) as publish_members,
    ):
        service.update_by_signed_up(invitee)

    invitation_repository.delete.assert_not_called()
    notification_service.notify_project_invited.assert_called_once_with(owner, invitee, project, invitation)
    publish_members.assert_called_once()


def test_signup_notification_is_not_duplicated() -> None:
    invitee = User.model_construct(id=SnowflakeID(1), email="invitee@example.com")
    owner = User.model_construct(id=SnowflakeID(2), email="owner@example.com")
    project = Project.model_construct(id=SnowflakeID(3), owner_id=owner.id, title="Invited project")
    invitation = ProjectInvitation.model_construct(
        id=SnowflakeID(4), project_id=project.id, email=invitee.email, token="pending-token"
    )
    repository = SimpleNamespace(
        project_invitation=SimpleNamespace(
            get_all_with_projects_by_email=Mock(return_value=[(invitation, project)]),
            get_all_by_project_with_user=Mock(return_value=[(invitation, invitee)]),
        ),
        user_notification=SimpleNamespace(get_project_invitation_notification=Mock(return_value=object())),
    )
    notification_service = SimpleNamespace(
        create_record_list=lambda records: [(type(record).__tablename__, record.id) for record in records],
        notify_project_invited=Mock(),
    )
    project_service = SimpleNamespace(get_api_assigned_user_list=Mock(return_value=[]))
    services = {
        NotificationService: notification_service,
        ProjectService: project_service,
    }
    service = ProjectInvitationService(lambda service_type: services[service_type], lambda _: None, repository)

    with (
        patch(
            "langboard_shared.domain.services.factory.ProjectInvitationService.InfraHelper.get_by_id_like",
            return_value=owner,
        ),
        patch(
            "langboard_shared.domain.services.factory.ProjectInvitationService.ProjectPublisher.assigned_users_updated"
        ),
    ):
        service.update_by_signed_up(invitee)

    notification_service.notify_project_invited.assert_not_called()
