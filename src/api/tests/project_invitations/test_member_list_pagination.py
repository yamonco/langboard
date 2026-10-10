from types import SimpleNamespace
from unittest.mock import Mock
from langboard_shared.domain.services.factory.ProjectInvitationService import ProjectInvitationService
from langboard_shared.domain.services.factory.ProjectService import ProjectService


def test_member_and_invitation_projections_apply_the_requested_limit() -> None:
    """List projections pass pagination to repositories instead of dropping it."""

    project = SimpleNamespace()
    assigned_rows = [(SimpleNamespace(api_response=lambda: {"name": "assigned"}), SimpleNamespace())]
    invitation_rows = [(SimpleNamespace(), SimpleNamespace(api_response=lambda: {"name": "invited"}))]
    repository = SimpleNamespace(
        project_assigned_user=SimpleNamespace(get_all_by_project=Mock(return_value=assigned_rows)),
        project_invitation=SimpleNamespace(get_all_by_project_with_user=Mock(return_value=invitation_rows)),
    )
    project_service = ProjectService(lambda _: None, lambda _: None, repository)
    invitation_service = ProjectInvitationService(lambda _: None, lambda _: None, repository)

    assert project_service.get_api_assigned_user_list(project, limit=5) == [{"name": "assigned"}]
    assert invitation_service.get_api_invited_user_list_by_project(project, limit=5) == [{"name": "invited"}]

    repository.project_assigned_user.get_all_by_project.assert_called_once_with(
        project,
        where_users_in=None,
        limit=5,
    )
    repository.project_invitation.get_all_by_project_with_user.assert_called_once_with(project, limit=5)
