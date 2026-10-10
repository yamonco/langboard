"""Audit log event contracts for governance changes.

One immutable envelope per governance-relevant mutation (actor,
tenant, resource, action, result, request context, before/after
diffs) with redaction of sensitive fields. Persistence and shipping
stay outside these contracts.
"""

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any


REDACTED = "***"


class AuditAction(str, Enum):
    """Governance actions that must leave an audit trail."""

    ORGANIZATION_CREATED = "organization.created"
    ORGANIZATION_SUSPENDED = "organization.suspended"
    ORGANIZATION_REACTIVATED = "organization.reactivated"
    MEMBER_ROLE_GRANTED = "member.role_granted"
    MEMBER_ROLE_REVOKED = "member.role_revoked"
    MEMBER_DEPROVISIONED = "member.deprovisioned"
    PROJECT_ASSIGNED = "project.assigned"
    PROJECT_UNASSIGNED = "project.unassigned"
    SCIM_USER_CREATED = "scim.user_created"
    SCIM_USER_DEACTIVATED = "scim.user_deactivated"
    IDENTITY_LINKED = "identity.linked"
    IDENTITY_UNLINKED = "identity.unlinked"


SENSITIVE_KEYS = {"password", "token", "secret", "authorization", "api_key"}


@dataclass(frozen=True)
class AuditEvent:
    """One immutable governance audit record."""

    event_uid: str
    action: AuditAction
    actor_uid: str
    organization_uid: str | None
    resource_type: str
    resource_uid: str
    result: str  # "success" | "denied" | "error"
    request_id: str = ""
    ip_address: str = ""
    before: dict[str, Any] = field(default_factory=dict)
    after: dict[str, Any] = field(default_factory=dict)
    recorded_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def __post_init__(self) -> None:
        if not self.event_uid:
            raise ValueError("event_uid is required")
        if not self.actor_uid:
            raise ValueError("actor_uid is required")
        if not self.resource_type.strip() or not self.resource_uid:
            raise ValueError("resource_type and resource_uid are required")
        if self.result not in ("success", "denied", "error"):
            raise ValueError(f"invalid result '{self.result}'")
        if self.recorded_at.tzinfo is None:
            raise ValueError("recorded_at must be timezone-aware")

    def redacted(self) -> "AuditEvent":
        """Return a copy with sensitive before/after values masked."""

        return AuditEvent(
            event_uid=self.event_uid,
            action=self.action,
            actor_uid=self.actor_uid,
            organization_uid=self.organization_uid,
            resource_type=self.resource_type,
            resource_uid=self.resource_uid,
            result=self.result,
            request_id=self.request_id,
            ip_address=self.ip_address,
            before=_redact(self.before),
            after=_redact(self.after),
            recorded_at=self.recorded_at,
        )

    def to_payload(self) -> dict[str, Any]:
        """Serialize for the audit sink."""

        event = self.redacted()
        return {
            "event_uid": event.event_uid,
            "action": event.action.value,
            "actor_uid": event.actor_uid,
            "organization_uid": event.organization_uid,
            "resource": {"type": event.resource_type, "uid": event.resource_uid},
            "result": event.result,
            "request_id": event.request_id,
            "ip_address": event.ip_address,
            "before": event.before,
            "after": event.after,
            "recorded_at": event.recorded_at.isoformat(),
        }


def _redact(value: dict[str, Any]) -> dict[str, Any]:
    redacted = {}
    for key, item in value.items():
        if any(marker in key.lower() for marker in SENSITIVE_KEYS):
            redacted[key] = REDACTED
        elif isinstance(item, dict):
            redacted[key] = _redact(item)
        else:
            redacted[key] = item
    return redacted


def diff_payload(before: dict[str, Any], after: dict[str, Any]) -> dict[str, Any]:
    """Minimal before/after pairs for changed top-level keys."""

    changes: dict[str, Any] = {}
    for key in sorted(set(before) | set(after)):
        old, new = before.get(key), after.get(key)
        if old != new:
            changes[key] = {"before": old, "after": new}
    return changes


def serialize_events(events: list[AuditEvent]) -> str:
    """Line-safe JSON serialization for audit shipping."""

    return json.dumps([event.to_payload() for event in events], ensure_ascii=False, sort_keys=True, default=str)
