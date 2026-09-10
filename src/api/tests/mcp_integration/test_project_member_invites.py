import os
from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import Mock, patch
import pytest


os.environ.setdefault("PROJECT_NAME", "langboard")

from langboard.mcp_integration import McpTool
from langboard.mcp_tools import ProjectMcp
from langboard.routes.board.BoardApi import search_project_member_candidates
from langboard_shared.core.db import DbSession
from langboard_shared.core.types import SnowflakeID
from langboard_shared.domain.models import Project, ProjectAssignedUser, ProjectRole, User
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
