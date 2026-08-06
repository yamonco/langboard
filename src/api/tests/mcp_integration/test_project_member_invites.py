import os
from types import SimpleNamespace
import pytest


os.environ.setdefault("PROJECT_NAME", "langboard")

from langboard.mcp_integration import McpTool
from langboard.mcp_tools import ProjectMcp
from langboard_shared.domain.models import User
from langboard_shared.domain.services.factory.ProjectInvitationService import (
    ProjectInvitationService,
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


def test_invite_tool_schema_and_legacy_replacement_tool_are_distinct() -> None:
    """Consumers can select additive invitations without changing the legacy contract."""

    invite_schema = McpTool.get_tool("invite_project_members")["input_schema"]
    assert invite_schema["required"] == ["project_uid", "emails"]
    assert McpTool.get_tool("update_project_members") is not None
