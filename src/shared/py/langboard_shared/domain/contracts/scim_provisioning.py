"""SCIM provisioning contracts for organization tenants.

Normalizes SCIM 2.0 request payloads (externalId, patch operations,
active toggles) into validated domain intents and plans the permission
revocation a deprovision must perform. Protocol handling stays in the
service layer; these contracts keep request validation pure.
"""

from dataclasses import dataclass, field
from enum import Enum


class ScimOperation(str, Enum):
    """SCIM PATCH operation kinds we understand."""

    REPLACE = "replace"
    ADD = "add"
    REMOVE = "remove"


class ProvisionIntent(str, Enum):
    """What a normalized SCIM request wants to do."""

    CREATE = "create"
    UPDATE = "update"
    DEACTIVATE = "deactivate"
    REACTIVATE = "reactivate"
    DELETE = "delete"


@dataclass(frozen=True)
class ScimUserRequest:
    """A normalized SCIM user payload."""

    external_id: str
    email: str
    firstname: str
    lastname: str
    active: bool = True

    def __post_init__(self) -> None:
        if not self.external_id.strip():
            raise ValueError("externalId is required")
        if "@" not in self.email:
            raise ValueError("email must be a valid address")

    def intent(self) -> ProvisionIntent:
        """Whether this payload represents activation or deactivation."""

        return ProvisionIntent.REACTIVATE if self.active else ProvisionIntent.DEACTIVATE


@dataclass(frozen=True)
class ScimPatchOperation:
    """One normalized SCIM PATCH operation."""

    op: ScimOperation
    path: str
    value: object = None

    def __post_init__(self) -> None:
        if not self.path.strip():
            raise ValueError("patch path is required")


@dataclass(frozen=True)
class RevocationPlan:
    """Permission teardown planned for a deactivated member."""

    user_uid: str
    organization_uid: str
    group_uids: tuple[str, ...] = field(default_factory=tuple)
    project_uids: tuple[str, ...] = field(default_factory=tuple)

    def is_empty(self) -> bool:
        """Whether there is anything to revoke."""

        return not (self.group_uids or self.project_uids)


def normalize_external_id(external_id: object) -> str:
    """Coerce an externalId into a stable trimmed string."""

    if external_id is None:
        return ""
    return str(external_id).strip()


def parse_patch_operations(payload: dict[str, object]) -> tuple[ScimPatchOperation, ...]:
    """Normalize SCIM PATCH 'Operations' into validated contracts."""

    raw = payload.get("Operations", [])
    if not isinstance(raw, list):
        raise ValueError("Operations must be a list")

    operations = []
    for item in raw:
        if not isinstance(item, dict):
            raise ValueError("each operation must be an object")
        op_name = str(item.get("op", "")).strip().lower()
        if op_name not in ScimOperation._value2member_map_:
            raise ValueError(f"unsupported SCIM op '{op_name}'")
        operations.append(
            ScimPatchOperation(
                op=ScimOperation(op_name),
                path=str(item.get("path", "")).strip(),
                value=item.get("value"),
            )
        )
    return tuple(operations)


def plan_revocation(
    *,
    user_uid: str,
    organization_uid: str,
    group_uids: tuple[str, ...] = (),
    project_uids: tuple[str, ...] = (),
) -> RevocationPlan:
    """Build the revocation plan for a deprovisioned member."""

    if not user_uid or not organization_uid:
        raise ValueError("user and organization are required")
    return RevocationPlan(
        user_uid=user_uid,
        organization_uid=organization_uid,
        group_uids=tuple(sorted(set(group_uids))),
        project_uids=tuple(sorted(set(project_uids))),
    )


def apply_deactivation(plan: RevocationPlan, memberships: dict[str, tuple[str, ...]]) -> dict[str, tuple[str, ...]]:
    """Drop the revoked user's group memberships (all when unscoped)."""

    if plan.user_uid not in memberships:
        return memberships
    updated = dict(memberships)
    if not plan.group_uids:
        del updated[plan.user_uid]
        return updated
    removed = set(plan.group_uids)
    updated[plan.user_uid] = tuple(group for group in updated[plan.user_uid] if group not in removed)
    return updated
