"""Organization role and permission model.

Org-level roles grant organization actions and can imply project
actions, keeping the existing project role system intact. Permission
resolution: explicit org role > org-implied defaults > project roles.
Pure contracts — storage lives in the models layer.
"""

from dataclasses import dataclass
from enum import Enum


ALL_GRANTED = "*"


class OrganizationAction(str, Enum):
    """Actions performable at the organization level."""

    MANAGE_MEMBERS = "manage_members"
    MANAGE_PROJECTS = "manage_projects"
    MANAGE_BILLING = "manage_billing"
    READ_AUDIT_LOG = "read_audit_log"
    VIEW_PROJECTS = "view_projects"


class ProjectAction(str, Enum):
    """Board-level actions implied by organization roles."""

    VIEW_CARDS = "view_cards"
    EDIT_CARDS = "edit_cards"
    MANAGE_PROJECT = "manage_project"


@dataclass(frozen=True)
class OrganizationRole:
    """One named organization role with granted actions."""

    uid: str
    name: str
    organization_actions: tuple[OrganizationAction, ...]
    implied_project_actions: tuple[ProjectAction, ...] = ()

    def grants(self, action: OrganizationAction) -> bool:
        """Whether this role grants an organization action."""

        return ALL_GRANTED in self._action_strings() or action in self.organization_actions

    def _action_strings(self) -> tuple[str, ...]:
        return tuple(action.value for action in self.organization_actions)

    def implies_project_action(self, action: ProjectAction) -> bool:
        """Whether this role implies a project action."""

        if ALL_GRANTED in self._action_strings():
            return True
        return action in self.implied_project_actions


OWNER_ROLE = OrganizationRole(
    uid="owner",
    name="Owner",
    organization_actions=tuple(OrganizationAction),
    implied_project_actions=tuple(ProjectAction),
)
ADMIN_ROLE = OrganizationRole(
    uid="admin",
    name="Admin",
    organization_actions=(
        OrganizationAction.MANAGE_MEMBERS,
        OrganizationAction.MANAGE_PROJECTS,
        OrganizationAction.READ_AUDIT_LOG,
        OrganizationAction.VIEW_PROJECTS,
    ),
    implied_project_actions=(ProjectAction.VIEW_CARDS, ProjectAction.EDIT_CARDS, ProjectAction.MANAGE_PROJECT),
)
MEMBER_ROLE = OrganizationRole(
    uid="member",
    name="Member",
    organization_actions=(OrganizationAction.VIEW_PROJECTS,),
    implied_project_actions=(ProjectAction.VIEW_CARDS, ProjectAction.EDIT_CARDS),
)
VIEWER_ROLE = OrganizationRole(
    uid="viewer",
    name="Viewer",
    organization_actions=(OrganizationAction.VIEW_PROJECTS,),
    implied_project_actions=(ProjectAction.VIEW_CARDS,),
)

BUILTIN_ROLES: dict[str, OrganizationRole] = {role.uid: role for role in (OWNER_ROLE, ADMIN_ROLE, MEMBER_ROLE, VIEWER_ROLE)}


@dataclass(frozen=True)
class OrganizationMembership:
    """A user's role inside one organization."""

    organization_uid: str
    user_uid: str
    role_uid: str

    def __post_init__(self) -> None:
        if not self.organization_uid or not self.user_uid or not self.role_uid:
            raise ValueError("membership fields are all required")
        if self.role_uid not in BUILTIN_ROLES:
            raise ValueError(f"unknown role {self.role_uid}")

    def role(self) -> OrganizationRole:
        """Resolve the builtin role of this membership."""

        return BUILTIN_ROLES[self.role_uid]


def resolve_organization_action(
    memberships: tuple[OrganizationMembership, ...],
    organization_uid: str,
    user_uid: str,
    action: OrganizationAction,
    *,
    is_platform_admin: bool = False,
) -> bool:
    """Whether a user may perform an org action (owner bypasses all)."""

    if is_platform_admin:
        return True
    for membership in memberships:
        if membership.organization_uid == organization_uid and membership.user_uid == user_uid:
            return membership.role().grants(action)
    return False


def resolve_project_action(
    memberships: tuple[OrganizationMembership, ...],
    organization_uid: str,
    user_uid: str,
    action: ProjectAction,
    project_actions: tuple[str, ...] = (),
    *,
    is_platform_admin: bool = False,
) -> bool:
    """Whether a user may perform a project action.

    Resolution order: platform admin > organization role implication >
    explicit project actions (which may use the "*" wildcard).
    """

    if is_platform_admin:
        return True
    for membership in memberships:
        if membership.organization_uid == organization_uid and membership.user_uid == user_uid:
            if membership.role().implies_project_action(action):
                return True
    return action.value in project_actions or ALL_GRANTED in project_actions


def effective_memberships(memberships: tuple[OrganizationMembership, ...], organization_uid: str) -> tuple[OrganizationMembership, ...]:
    """Filter memberships to one organization, deterministic order."""

    return tuple(
        sorted(
            (membership for membership in memberships if membership.organization_uid == organization_uid),
            key=lambda membership: (membership.user_uid, membership.role_uid),
        )
    )
