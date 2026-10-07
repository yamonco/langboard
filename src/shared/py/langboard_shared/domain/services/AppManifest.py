"""Host-owned App declarations; discovery never installs code or grants access."""

from dataclasses import dataclass
from types import MappingProxyType
from ..models.ProjectRole import ProjectRoleAction
from .AppWorkflowPolicy import APP_WORKFLOW_REQUIREMENTS, WorkflowRequirements


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

    def catalog_fields(self) -> dict:
        requirements = self.workflow_requirements
        return {
            "key": self.key,
            "name": self.name,
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
        ),
        "glitchtip": AppManifest(
            "glitchtip",
            "GlitchTip",
            ("organization", "project"),
            ("resources.read", "signals.read", "workflow.transition"),
            APP_WORKFLOW_REQUIREMENTS["glitchtip"],
        ),
        "dokploy": AppManifest(
            "dokploy",
            "Dokploy",
            ("project", "environment", "application", "compose"),
            ("resources.read", "signals.read", "deployments.read"),
        ),
    }
)
