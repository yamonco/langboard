import os
from types import SimpleNamespace
from unittest.mock import ANY, Mock, patch
import pytest


os.environ.setdefault("PROJECT_NAME", "langboard")

from langboard.mcp_integration import McpTool
from langboard.mcp_tools import ProjectMcp
from langboard_shared.domain.models import IdentityProvider, User
from langboard_shared.domain.services.factory.IdentityLinkService import IdentityLinkService
from langboard_shared.domain.services.factory.ProjectInvitationService import (
    InvitationRelatedResult,
    ProjectInvitationService,
)
from langboard_shared.domain.services.factory.ProjectService import ProjectService


def test_additive_invitation_data_preserves_existing_members_and_invites() -> None:
    """Additive discovery selects only new recipients and records no removals."""

    assigned_user = SimpleNamespace(id=1)
    assigned_relationship = SimpleNamespace(id=11)
    new_user = SimpleNamespace(id=2)
    pending_invitation = object()
    users = {
        "assigned@example.com": assigned_user,
        "new@example.com": new_user,
    }
    repository = SimpleNamespace(
        user=SimpleNamespace(get_by_email=lambda email: (users.get(email), None)),
        project_assigned_user=SimpleNamespace(
            get_by_user_and_project=lambda user, _project: assigned_relationship if user is assigned_user else None
        ),
        project_invitation=SimpleNamespace(
            get_by_project_and_email=lambda _project, email: (
                pending_invitation if email == "pending@example.com" else None
            )
        ),
    )
    service = ProjectInvitationService(lambda _: None, lambda _: None, repository)

    result = service.get_additive_invitation_related_data(
        object(),
        ["assigned@example.com", "pending@example.com", "new@example.com"],
    )

    assert result.emails_should_invite == {"new@example.com"}
    assert result.users_by_email == {"new@example.com": new_user}
    assert result.emails_should_remove == {}
    assert result.user_ids_should_delete == set()
    assert result.assigned_ids_should_delete == set()


def test_invite_tool_normalizes_bounds_and_returns_safe_aggregate() -> None:
    """The MCP boundary deduplicates recipients and never returns their values."""

    calls: list[list[str]] = []
    service = SimpleNamespace(
        project=SimpleNamespace(
            invite_assigned_users=lambda _user, _project, emails: (
                calls.append(emails) or {"requested_count": len(emails), "changed_count": 1, "status": "updated"}
            )
        )
    )
    user = User.model_construct()

    result = ProjectMcp.invite_project_members("project", user, [" New@Example.com ", "new@example.com"], service)

    assert calls == [["new@example.com"]]
    assert result == {"requested_count": 1, "changed_count": 1, "status": "updated"}
    assert "example.com" not in str(result)

    with pytest.raises(ValueError, match="between 1 and 10"):
        ProjectMcp.invite_project_members("project", user, [], service)
    with pytest.raises(ValueError, match="Invalid email"):
        ProjectMcp.invite_project_members("project", user, ["not-an-email"], service)
    with pytest.raises(ValueError, match="between 1 and 10"):
        ProjectMcp.invite_project_members(
            "project", user, [f"member-{index}@example.com" for index in range(11)], service
        )
    with pytest.raises(ValueError, match="between 1 and 10"):
        ProjectMcp.invite_project_members("project", user, ["same@example.com"] * 11, service)

    missing_service = SimpleNamespace(project=SimpleNamespace(invite_assigned_users=lambda *_args: None))
    with pytest.raises(ValueError, match="Project not found"):
        ProjectMcp.invite_project_members("missing", user, ["member@example.com"], missing_service)


def test_project_people_search_hides_email_and_addition_is_immediate() -> None:
    """Existing people can be selected and added without an invitation email."""

    employee = SimpleNamespace(
        firstname="Grace",
        lastname="Lee",
        username="grace",
        email="grace@example.com",
        deleted_at=None,
        get_uid=lambda: "person-1",
    )
    calls: list[list[object]] = []
    service = SimpleNamespace(
        project=SimpleNamespace(
            search_member_candidates=lambda _user, _project, query: [employee] if query == "Gr" else [],
            add_existing_assigned_users=lambda _user, _project, users: calls.append(users)
            or {"requested_count": len(users), "changed_count": 1, "status": "updated"},
        ),
        user=SimpleNamespace(get_by_id_like=lambda uid: employee if uid == "person-1" else None),
    )
    actor = User.model_construct()

    found = ProjectMcp.search_project_people("project", " Gr ", actor, service)
    added = ProjectMcp.add_project_people("project", ["person-1"], actor, service)

    assert found == {"items": [{"uid": "person-1", "firstname": "Grace", "lastname": "Lee", "username": "grace"}]}
    assert "example.com" not in str(found)
    assert added == {"requested_count": 1, "changed_count": 1, "status": "updated"}
    assert calls == [[employee]]


def test_project_people_search_compacts_real_api_projection_without_email() -> None:
    """The MCP path accepts the dict shape returned by the native candidate service."""

    projection = {
        "type": User.USER_TYPE,
        "uid": "person-1",
        "firstname": "Grace",
        "lastname": "Lee",
        "username": "grace",
        "email": "grace@example.com",
    }
    service = SimpleNamespace(project=SimpleNamespace(search_member_candidates=lambda *_args: [projection]))

    result = ProjectMcp.search_project_people("project", "Gr", User.model_construct(), service)

    assert result == {"items": [{"uid": "person-1", "firstname": "Grace", "lastname": "Lee", "username": "grace"}]}
    assert "example.com" not in str(result)


def test_project_people_rejects_short_search_missing_or_deleted_selection() -> None:
    """Directory actions stay bounded and cannot add a deleted account."""

    actor = User.model_construct()
    deleted = User.model_construct(deleted_at=object())
    service = SimpleNamespace(
        project=SimpleNamespace(search_member_candidates=lambda *_args: [], invite_assigned_users=lambda *_args: None),
        user=SimpleNamespace(get_by_id_like=lambda uid: deleted if uid == "deleted" else None),
    )

    with pytest.raises(ValueError, match="at least two"):
        ProjectMcp.search_project_people("project", "x", actor, service)
    with pytest.raises(ValueError, match="no longer exist"):
        ProjectMcp.add_project_people("project", ["missing"], actor, service)
    with pytest.raises(ValueError, match="no longer exist"):
        ProjectMcp.add_project_people("project", ["deleted"], actor, service)


def test_additive_retry_is_a_complete_noop() -> None:
    """An already-assigned or pending request emits no repeated side effects."""

    project = object()
    invitation_service = SimpleNamespace(
        get_additive_invitation_related_data=Mock(return_value=InvitationRelatedResult()),
        invite_emails=Mock(),
    )
    assigned_users = Mock()
    repository = SimpleNamespace(project_assigned_user=SimpleNamespace(get_all_by_project=assigned_users))
    service = ProjectService(lambda _: None, lambda _: None, repository)

    with (
        patch(
            "langboard_shared.domain.services.factory.ProjectService.InfraHelper.get_by_id_like",
            return_value=project,
        ),
        patch.object(service, "_get_service_by_name", return_value=invitation_service),
    ):
        result = service.invite_assigned_users(User.model_construct(), project, ["pending@example.com"])

    assert result == {"requested_count": 1, "changed_count": 0, "status": "unchanged"}
    invitation_service.invite_emails.assert_not_called()
    assigned_users.assert_not_called()


def test_existing_member_addition_bypasses_invitation_and_preserves_members() -> None:
    """A known account receives project access immediately without an invite email."""

    project = SimpleNamespace(id=10)
    actor = User.model_construct()
    employee = SimpleNamespace(id=20, api_response=lambda: {"name": "Grace"})
    existing = SimpleNamespace(id=30, api_response=lambda: {"name": "Existing"})
    assigned_rows = [(existing, object()), (employee, object())]
    assigned_repository = SimpleNamespace(
        get_all_by_project=Mock(side_effect=[[(existing, object())], assigned_rows]),
        ensure_assigned=Mock(return_value=(object(), True)),
    )
    role_repository = SimpleNamespace(project=SimpleNamespace(grant_default=Mock()))
    relationship_repository = SimpleNamespace(ensure_project_relationships=Mock())
    invitation_service = SimpleNamespace(get_api_invited_user_list_by_project=Mock(return_value=[]))
    repository = SimpleNamespace(
        project_assigned_user=assigned_repository,
        role=role_repository,
        project_user_relationship=relationship_repository,
    )
    service = ProjectService(lambda _: None, lambda _: None, repository)

    with (
        patch(
            "langboard_shared.domain.services.factory.ProjectService.InfraHelper.get_by_id_like", return_value=project
        ),
        patch.object(service, "_get_service_by_name", return_value=invitation_service),
        patch("langboard_shared.domain.services.factory.ProjectService.ProjectPublisher.assigned_users_updated"),
        patch("langboard_shared.domain.services.factory.ProjectService.ProjectPublisher.assigned_to_users"),
        patch("langboard_shared.domain.services.factory.ProjectService.ProjectActivityTask.project_assigned_users_updated"),
    ):
        result = service.add_existing_assigned_users(actor, project, [employee])

    assert result == {"requested_count": 1, "changed_count": 1, "status": "updated"}
    assigned_repository.ensure_assigned.assert_called_once_with(project, employee)
    role_repository.project.grant_default.assert_called_once_with(user_id=20, project_id=10)
    invitation_service.get_api_invited_user_list_by_project.assert_called_once_with(project)


def test_federated_active_account_is_added_without_an_email_invitation() -> None:
    """Federated accounts become members immediately while classic accounts retain the invite flow."""

    target = User.model_construct(id=1, activated_at=object())
    invitation = InvitationRelatedResult()
    invitation.emails_should_invite.add("employee@example.com")
    invitation.users_by_email["employee@example.com"] = target
    assigned = Mock()
    email_service = SimpleNamespace(send_template=Mock())
    identity_link = SimpleNamespace(
        get_by_user_provider=lambda _user, provider: object() if provider is IdentityProvider.Oidc else None
    )
    service = ProjectInvitationService(
        lambda service_type: identity_link if service_type is IdentityLinkService else email_service,
        lambda _name: None,
        SimpleNamespace(),
    )
    setattr(service, "_ProjectInvitationService__assign_project_user", assigned)

    with patch(
        "langboard_shared.domain.services.factory.ProjectInvitationService.InfraHelper.get_by_id_like",
        return_value=SimpleNamespace(),
    ):
        service.invite_emails(User.model_construct(), "project", invitation)

    assigned.assert_called_once_with(ANY, target)
    email_service.send_template.assert_not_called()


def test_invite_tool_schema_and_legacy_replacement_tool_are_distinct() -> None:
    """Consumers can select additive invitations without changing the legacy contract."""

    invite_schema = McpTool.get_tool("invite_project_members")["input_schema"]
    assert invite_schema["required"] == ["project_uid", "emails"]
    assert McpTool.get_tool("update_project_members") is not None
