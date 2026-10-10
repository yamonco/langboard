"""Host-owned App declarations; discovery never installs code or grants access."""

from dataclasses import dataclass
from types import MappingProxyType
from ..models.ProjectRole import ProjectRoleAction
from .AppWorkflowPolicy import APP_WORKFLOW_REQUIREMENTS, WorkflowRequirements


@dataclass(frozen=True)
class AppSignalPolicy:
    """Host-installed adapter declaration; never a caller-supplied access grant."""

    event_types: tuple[str, ...]
    resource_types: tuple[str, ...]
    required_capabilities: tuple[str, ...] = ("signals.read",)
    requires_empty_commit: bool = False
    requires_commit: bool = False
    time_basis: str = "provider_occurrence"
    outcome_states: tuple[tuple[str, str], ...] = (
        ("success", "passed"), ("failure", "failed"), ("timed_out", "failed"),
    )


@dataclass(frozen=True)
class AppManifest:
    key: str
    name: str
    resource_types: tuple[str, ...]
    capabilities: tuple[str, ...]
    workflow_requirements: WorkflowRequirements | None = None
    # Current host role actions, not provider OAuth scopes or granted permissions.
    read_permission: ProjectRoleAction = ProjectRoleAction.Read
    configure_permission: ProjectRoleAction = ProjectRoleAction.Update
    signal_schema_version: int = 1
    signal_policy: AppSignalPolicy | None = None
    version: str | None = None
    description: str = ""
    panel: dict | None = None

    def catalog_fields(self) -> dict:
        requirements = self.workflow_requirements
        return {
            "key": self.key,
            "name": self.name,
            "version": self.version,
            "description": self.description,
            "panel": self.panel,
            "resource_types": list(self.resource_types),
            "capabilities": list(self.capabilities),
            "permissions": {"read": self.read_permission.value, "configure": self.configure_permission.value},
            "workflow_requirements": None
            if requirements is None
            else {
                "required": list(requirements.required),
                "optional": list(requirements.optional),
            },
            "signal_schema": {
                "version": self.signal_schema_version,
                "required": ["event_id", "event_type", "occurred_at", "connection_uid", "resource_uid"],
            },
            # Provider onboarding and signal consumers must exist before this becomes true.
            "connection_setup_available": False,
        }


APP_MANIFESTS = MappingProxyType(
    {
        "github": AppManifest(
            "github",
            "GitHub",
            ("repository",),
            ("resources.read", "signals.read", "workflow.transition"),
            APP_WORKFLOW_REQUIREMENTS["github"],
            signal_policy=AppSignalPolicy(("check.completed",), ("repository",), requires_commit=True),
        ),
        "glitchtip": AppManifest(
            "glitchtip",
            "GlitchTip",
            ("organization", "project"),
            ("resources.read", "signals.read", "workflow.transition"),
            APP_WORKFLOW_REQUIREMENTS["glitchtip"],
            signal_policy=AppSignalPolicy(
                ("issue.status_observed",), ("project",), ("signals.read", "resources.read"),
                requires_empty_commit=True, time_basis="observation",
                outcome_states=(("unresolved", "failed"), ("resolved", "resolved"), ("ignored", "ignored")),
            ),
        ),
        "dokploy": AppManifest(
            "dokploy",
            "Dokploy",
            ("project", "environment", "application", "compose"),
            ("resources.read", "signals.read", "deployments.read"),
            signal_policy=AppSignalPolicy(
                ("deployment.queued", "deployment.started", "deployment.succeeded", "deployment.failed", "deployment.cancelled"),
                ("application", "compose"), ("signals.read", "deployments.read"), requires_empty_commit=True,
                outcome_states=(
                    ("success", "passed"), ("failure", "failed"), ("timed_out", "failed"),
                    ("queued", "queued"), ("running", "running"), ("cancelled", "cancelled"),
                ),
            ),
        ),
    }
)
