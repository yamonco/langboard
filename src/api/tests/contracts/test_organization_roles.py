import os


os.environ.setdefault("PROJECT_NAME", "langboard")

import pytest  # noqa: E402
from langboard_shared.domain.contracts.organization_roles import (  # noqa: E402
    ADMIN_ROLE,
    OWNER_ROLE,
    VIEWER_ROLE,
    OrganizationAction,
    OrganizationMembership,
    ProjectAction,
    effective_memberships,
    resolve_organization_action,
    resolve_project_action,
)


def membership(role_uid: str, user_uid: str = "u1", org_uid: str = "org1") -> OrganizationMembership:
    return OrganizationMembership(organization_uid=org_uid, user_uid=user_uid, role_uid=role_uid)


class TestBuiltinRoles:
    def test_owner_grants_everything(self):
        assert OWNER_ROLE.grants(OrganizationAction.MANAGE_BILLING)
        assert OWNER_ROLE.implies_project_action(ProjectAction.MANAGE_PROJECT)

    def test_viewer_is_read_only(self):
        assert VIEWER_ROLE.grants(OrganizationAction.VIEW_PROJECTS)
        assert not VIEWER_ROLE.grants(OrganizationAction.MANAGE_MEMBERS)
        assert VIEWER_ROLE.implies_project_action(ProjectAction.VIEW_CARDS)
        assert not VIEWER_ROLE.implies_project_action(ProjectAction.EDIT_CARDS)

    def test_admin_cannot_manage_billing(self):
        assert not ADMIN_ROLE.grants(OrganizationAction.MANAGE_BILLING)


class TestMembership:
    def test_rejects_unknown_role(self):
        with pytest.raises(ValueError):
            membership("warlord")

    def test_rejects_blank_fields(self):
        with pytest.raises(ValueError):
            OrganizationMembership(organization_uid="", user_uid="u", role_uid="member")


class TestResolveOrganizationAction:
    def test_member_cannot_manage(self):
        assert not resolve_organization_action((membership("member"),), "org1", "u1", OrganizationAction.MANAGE_MEMBERS)

    def test_admin_can_manage_members(self):
        assert resolve_organization_action((membership("admin"),), "org1", "u1", OrganizationAction.MANAGE_MEMBERS)

    def test_platform_admin_bypasses(self):
        assert resolve_organization_action((), "org1", "u1", OrganizationAction.MANAGE_BILLING, is_platform_admin=True)

    def test_other_org_membership_ignored(self):
        assert not resolve_organization_action((membership("admin", org_uid="org2"),), "org1", "u1", OrganizationAction.MANAGE_MEMBERS)


class TestResolveProjectAction:
    def test_org_role_implies_project_action(self):
        assert resolve_project_action((membership("member"),), "org1", "u1", ProjectAction.EDIT_CARDS)

    def test_project_actions_wildcard(self):
        assert resolve_project_action((), "org1", "u1", ProjectAction.EDIT_CARDS, project_actions=("*",))

    def test_explicit_project_action(self):
        assert resolve_project_action((), "org1", "u1", ProjectAction.VIEW_CARDS, project_actions=("view_cards",))

    def test_no_membership_no_grant(self):
        assert not resolve_project_action((), "org1", "u1", ProjectAction.EDIT_CARDS)


class TestEffectiveMemberships:
    def test_filters_and_orders(self):
        memberships = (membership("viewer", "u2"), membership("admin", "u1"), membership("member", "u1", org_uid="org2"))
        assert [m.user_uid for m in effective_memberships(memberships, "org1")] == ["u1", "u2"]
