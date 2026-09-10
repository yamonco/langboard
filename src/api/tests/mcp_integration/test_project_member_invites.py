import os
from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import ANY, Mock, patch
import pytest


os.environ.setdefault("PROJECT_NAME", "langboard")

from langboard.mcp_integration import McpTool
from langboard.mcp_tools import ProjectMcp
from langboard.routes.board.BoardApi import search_project_member_candidates
from langboard.routes.board.forms.Project import InviteProjectMemberForm
from langboard_shared.core.db import DbSession
from langboard_shared.core.types import SnowflakeID
from langboard_shared.domain.models import IdentityProvider, Project, ProjectAssignedUser, ProjectRole, User
from langboard_shared.domain.models.ProjectRole import ProjectRoleAction
from langboard_shared.domain.services.factory.ProjectInvitationService import (
    InvitationRelatedResult,
    ProjectInvitationService,
)
from langboard_shared.domain.services.factory.ProjectService import ProjectService
from langboard_shared.filter import RoleFilter
from langboard_shared.infrastructure.repositories.factory.ProjectAssignedUserRepository import (
    ProjectAssignedUserRepository,
)


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


def test_additive_invitation_reports_a_concurrent_duplicate_as_unchanged() -> None:
    """A repository race loser reports no change after the atomic insert is skipped."""

    project = object()
    invitation_data = InvitationRelatedResult()
    invitation_data.emails_should_invite.add("pending@example.com")

    def lose_insert_race(_user: User, _project: object, result: InvitationRelatedResult) -> bool:
        result.applied_count = 0
        return True

    invitation_service = SimpleNamespace(
        get_additive_invitation_related_data=Mock(return_value=invitation_data),
        invite_emails=Mock(side_effect=lose_insert_race),
        get_api_invited_user_list_by_project=Mock(return_value=[]),
    )
    assigned_users = Mock(return_value=[])
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
    role_repository = SimpleNamespace(project=SimpleNamespace(grant_all=Mock()))
    relationship_repository = SimpleNamespace(ensure_project_relationships=Mock())
    user_repository = SimpleNamespace(get_direct_project_member_candidates=Mock(return_value=[employee]))
    user_service = SimpleNamespace(can_search_all_users=Mock(return_value=False))
    invitation_service = SimpleNamespace(get_api_invited_user_list_by_project=Mock(return_value=[]))
    repository = SimpleNamespace(
        project_assigned_user=assigned_repository,
        role=role_repository,
        project_user_relationship=relationship_repository,
        user=user_repository,
    )
    service = ProjectService(lambda _: None, lambda _: None, repository)

    with (
        patch(
            "langboard_shared.domain.services.factory.ProjectService.InfraHelper.get_by_id_like",
            return_value=project,
        ),
        patch.object(
            service,
            "_get_service_by_name",
            side_effect=lambda name: user_service if name == "user" else invitation_service,
        ),
        patch.object(
            service,
            "_ProjectService__organization_identities",
            return_value=[(IdentityProvider.Oidc, "https://issuer.example")],
        ),
        patch("langboard_shared.domain.services.factory.ProjectService.ProjectPublisher.assigned_users_updated"),
        patch("langboard_shared.domain.services.factory.ProjectService.ProjectPublisher.assigned_to_users"),
        patch(
            "langboard_shared.domain.services.factory.ProjectService.ProjectActivityTask.project_assigned_users_updated"
        ),
    ):
        result = service.add_existing_assigned_users(actor, project, [employee])

    assert result == {"requested_count": 1, "changed_count": 1, "status": "updated"}
    assigned_repository.ensure_assigned.assert_called_once_with(project, employee)
    user_repository.get_direct_project_member_candidates.assert_called_once_with(
        actor,
        [employee],
        can_search_all_users=False,
        organization_identities=[(IdentityProvider.Oidc, "https://issuer.example")],
    )
    role_repository.project.grant_all.assert_called_once_with(user_id=20, project_id=10)
    invitation_service.get_api_invited_user_list_by_project.assert_called_once_with(project)


def test_active_email_match_outside_candidate_scope_stays_on_invitation_track() -> None:
    """An existing non-admin target still receives an invitation instead of direct access."""

    actor = User.model_construct(is_admin=False, preferred_lang="en-US", firstname="Actor", lastname="User")
    target = User.model_construct(id=1, activated_at=object(), preferred_lang="en-US", firstname="Target")
    project = SimpleNamespace(title="Project")
    created_invitation = object()
    invitation = InvitationRelatedResult()
    invitation.emails_should_invite.add("employee@example.com")
    invitation.users_by_email["employee@example.com"] = target
    assigned = Mock()
    email_service = SimpleNamespace(send_template=Mock())
    notification_service = SimpleNamespace(notify_project_invited=Mock())
    repository = SimpleNamespace(
        project_invitation=SimpleNamespace(create_if_missing=Mock(return_value=created_invitation))
    )
    service = ProjectInvitationService(
        lambda service_type: email_service if service_type.__name__ == "EmailService" else notification_service,
        lambda _name: None,
        repository,
    )
    setattr(service, "_ProjectInvitationService__assign_project_user", assigned)

    with (
        patch(
            "langboard_shared.domain.services.factory.ProjectInvitationService.InfraHelper.get_by_id_like",
            return_value=project,
        ),
        patch.object(
            service, "_ProjectInvitationService__create_invitation_token_url", return_value="https://example.test"
        ),
    ):
        service.invite_emails(actor, "project", invitation)

    assigned.assert_not_called()
    repository.project_invitation.create_if_missing.assert_called_once_with(
        project,
        "employee@example.com",
        ANY,
    )
    notification_service.notify_project_invited.assert_called_once_with(actor, target, project, created_invitation)
    email_service.send_template.assert_called_once()


def test_federated_member_uid_uses_direct_addition_without_email() -> None:
    """The explicit organization-member track never creates or sends an invitation."""

    actor = User.model_construct(is_admin=False, preferred_lang="en-US", firstname="Actor", lastname="User")
    target = User.model_construct(id=SnowflakeID(1), activated_at=object(), preferred_lang="en-US", firstname="Target")
    project = SimpleNamespace(title="Project")
    invitation = InvitationRelatedResult()
    invitation.emails_should_invite.add("employee@example.com")
    invitation.users_by_email["employee@example.com"] = target
    assigned = Mock()
    email_service = SimpleNamespace(send_template=Mock())
    notification_service = SimpleNamespace(notify_project_invited=Mock())
    repository = SimpleNamespace(project_invitation=SimpleNamespace(create_if_missing=Mock()))
    service = ProjectInvitationService(
        lambda service_type: email_service if service_type.__name__ == "EmailService" else notification_service,
        lambda _name: None,
        repository,
    )
    setattr(service, "_ProjectInvitationService__assign_project_user", assigned)

    with patch(
        "langboard_shared.domain.services.factory.ProjectInvitationService.InfraHelper.get_by_id_like",
        return_value=project,
    ):
        service.invite_emails(actor, "project", invitation, direct_user_ids={target.id})

    assigned.assert_called_once_with(project, target)
    repository.project_invitation.create_if_missing.assert_not_called()
    notification_service.notify_project_invited.assert_not_called()
    email_service.send_template.assert_not_called()


def test_member_update_form_keeps_direct_and_external_tracks_distinct() -> None:
    form = InviteProjectMemberForm(member_uids=["member-a"], emails=["guest@example.com"])

    assert form.member_uids == ["member-a"]
    assert form.emails == ["guest@example.com"]


def test_member_update_routes_federated_people_to_direct_addition() -> None:
    project = SimpleNamespace(id=10)
    actor = User.model_construct(id=SnowflakeID(11))
    employee = User.model_construct(id=SnowflakeID(20), email="employee@example.com")
    assigned_rows = [(employee, object())]
    assigned_repository = SimpleNamespace(
        get_all_by_project=Mock(side_effect=[[], assigned_rows]),
        delete_all_by_project_and_users=Mock(),
    )
    relationship_repository = SimpleNamespace(ensure_project_relationships=Mock())
    user_repository = SimpleNamespace(get_direct_project_member_candidates=Mock(return_value=[employee]))
    invitation_data = InvitationRelatedResult()
    invitation_service = SimpleNamespace(
        get_invitation_related_data=Mock(return_value=invitation_data),
        invite_emails=Mock(return_value=True),
        get_api_invited_user_list_by_project=Mock(return_value=[]),
    )
    user_service = SimpleNamespace(can_search_all_users=Mock(return_value=False))
    service = ProjectService(
        lambda _type: None,
        lambda _name: None,
        SimpleNamespace(
            project_assigned_user=assigned_repository,
            project_user_relationship=relationship_repository,
            user=user_repository,
        ),
    )

    with (
        patch(
            "langboard_shared.domain.services.factory.ProjectService.InfraHelper.get_by_id_like",
            return_value=project,
        ),
        patch.object(
            service,
            "_get_service_by_name",
            side_effect=lambda name: user_service if name == "user" else invitation_service,
        ),
        patch.object(
            service,
            "_ProjectService__organization_identities",
            return_value=[(IdentityProvider.Oidc, "https://issuer.example")],
        ),
        patch("langboard_shared.domain.services.factory.ProjectService.ProjectPublisher.assigned_users_updated"),
        patch("langboard_shared.domain.services.factory.ProjectService.ProjectPublisher.assigned_to_users"),
        patch(
            "langboard_shared.domain.services.factory.ProjectService.ProjectActivityTask.project_assigned_users_updated"
        ),
    ):
        result = service.update_assigned_users(
            actor,
            project,
            ["guest@example.com"],
            direct_members=[employee],
        )

    assert result is True
    invitation_service.get_invitation_related_data.assert_called_once_with(
        project,
        ["guest@example.com", "employee@example.com"],
    )
    invitation_service.invite_emails.assert_called_once_with(
        actor,
        project,
        invitation_data,
        direct_user_ids={employee.id},
    )


def test_existing_member_addition_rejects_arbitrary_uid_outside_candidate_scope() -> None:
    """Resolving a real user object is insufficient without relationship-scoped eligibility."""

    project = SimpleNamespace(id=10)
    actor = User.model_construct(id=11)
    unrelated = User.model_construct(id=20, activated_at=object())
    assigned_repository = SimpleNamespace(
        get_all_by_project=Mock(),
        ensure_assigned=Mock(),
    )
    user_repository = SimpleNamespace(get_direct_project_member_candidates=Mock(return_value=[]))
    service = ProjectService(
        lambda _type: None,
        lambda _name: None,
        SimpleNamespace(project_assigned_user=assigned_repository, user=user_repository),
    )
    user_service = SimpleNamespace(can_search_all_users=Mock(return_value=False))

    with (
        patch(
            "langboard_shared.domain.services.factory.ProjectService.InfraHelper.get_by_id_like",
            return_value=project,
        ),
        patch.object(service, "_get_service_by_name", return_value=user_service),
        patch.object(
            service,
            "_ProjectService__organization_identities",
            return_value=[(IdentityProvider.Oidc, "https://issuer.example")],
        ),
        pytest.raises(ValueError, match="not eligible"),
    ):
        service.add_existing_assigned_users(actor, project, [unrelated])

    assigned_repository.get_all_by_project.assert_not_called()
    assigned_repository.ensure_assigned.assert_not_called()


def test_external_invitation_acceptance_grants_card_work_without_admin_access() -> None:
    """Accepted guests can create and update cards but cannot manage or delete project data."""

    project = SimpleNamespace(id=10)
    guest = User.model_construct(id=20)
    grant = Mock()
    repository = SimpleNamespace(
        project_assigned_user=SimpleNamespace(
            ensure_assigned=Mock(return_value=(object(), True)),
            get_all_by_project=Mock(return_value=[]),
        ),
        project_invitation=SimpleNamespace(get_all_by_project_with_user=Mock(return_value=[])),
        project_user_relationship=SimpleNamespace(ensure_project_relationships=Mock()),
        role=SimpleNamespace(project=SimpleNamespace(grant=grant)),
    )
    project_service = SimpleNamespace(get_api_assigned_user_list=Mock(return_value=[]))
    service = ProjectInvitationService(
        lambda service_type: project_service if service_type is ProjectService else None,
        lambda _name: None,
        repository,
    )

    with (
        patch("langboard_shared.domain.services.factory.ProjectInvitationService.ProjectPublisher.assigned_to_users"),
        patch("langboard_shared.domain.services.factory.ProjectInvitationService.ProjectInvitationPublisher.accepted"),
        patch(
            "langboard_shared.domain.services.factory.ProjectInvitationService.ProjectActivityTask.project_invited_user_accepted"
        ),
    ):
        service._ProjectInvitationService__assign_project_user(project, guest)

    grant.assert_called_once_with(
        actions=[
            ProjectRoleAction.Read.value,
            ProjectRoleAction.CardWrite.value,
            ProjectRoleAction.CardUpdate.value,
        ],
        user_id=guest.id,
        project_id=project.id,
    )


def test_invitation_acceptance_preserves_an_existing_members_role() -> None:
    """A stale invitation cannot downgrade a member who already has stronger access."""

    project = SimpleNamespace(id=10)
    member = User.model_construct(id=20)
    grant = Mock()
    repository = SimpleNamespace(
        project_assigned_user=SimpleNamespace(
            ensure_assigned=Mock(return_value=(object(), False)),
            get_all_by_project=Mock(return_value=[]),
        ),
        project_invitation=SimpleNamespace(get_all_by_project_with_user=Mock(return_value=[])),
        project_user_relationship=SimpleNamespace(ensure_project_relationships=Mock()),
        role=SimpleNamespace(project=SimpleNamespace(grant=grant)),
    )
    project_service = SimpleNamespace(get_api_assigned_user_list=Mock(return_value=[]))
    service = ProjectInvitationService(
        lambda service_type: project_service if service_type is ProjectService else None,
        lambda _name: None,
        repository,
    )

    with (
        patch("langboard_shared.domain.services.factory.ProjectInvitationService.ProjectPublisher.assigned_to_users"),
        patch("langboard_shared.domain.services.factory.ProjectInvitationService.ProjectInvitationPublisher.accepted"),
        patch(
            "langboard_shared.domain.services.factory.ProjectInvitationService.ProjectActivityTask.project_invited_user_accepted"
        ),
    ):
        service._ProjectInvitationService__assign_project_user(project, member)

    grant.assert_not_called()


def test_invite_tool_schema_and_legacy_replacement_tool_are_distinct() -> None:
    """Consumers can select additive invitations without changing the legacy contract."""

    invite_schema = McpTool.get_tool("invite_project_members")["input_schema"]
    assert invite_schema["required"] == ["project_uid", "emails"]
    assert McpTool.get_tool("update_project_members") is not None


def test_member_candidate_search_requires_project_update() -> None:
    role_model, actions, _, _ = RoleFilter.get_filtered(search_project_member_candidates)

    assert role_model is ProjectRole
    assert actions == [ProjectRoleAction.Update.value]


def test_member_assignment_locks_project_before_checking_for_duplicates(monkeypatch: pytest.MonkeyPatch) -> None:
    """Concurrent invitation acceptance is serialized on the owning project row."""

    project = Project.model_construct(id=SnowflakeID(1))
    user = User.model_construct(id=SnowflakeID(2))
    existing = ProjectAssignedUser.model_construct(
        id=SnowflakeID(3),
        project_id=project.id,
        user_id=user.id,
    )
    statements: list[object] = []
    inserts: list[ProjectAssignedUser] = []

    class Result:
        def __init__(self, value: object | None) -> None:
            self.value = value

        def first(self) -> object | None:
            return self.value

    class Database:
        def exec(self, statement: object) -> Result:
            statements.append(statement)
            return Result(project if len(statements) == 1 else existing)

        def insert(self, assigned_user: ProjectAssignedUser) -> None:
            inserts.append(assigned_user)

    @contextmanager
    def use_database(*, readonly: bool):
        assert readonly is False
        yield Database()

    monkeypatch.setattr(DbSession, "use", use_database)
    repository = ProjectAssignedUserRepository(lambda *_: None, lambda *_: None)

    assigned_user, created = repository.ensure_assigned(project, user)

    assert assigned_user is existing
    assert created is False
    assert getattr(statements[0], "_for_update_arg", None) is not None
    assert inserts == []
