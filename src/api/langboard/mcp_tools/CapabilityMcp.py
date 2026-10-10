"""Runtime capability diagnostics for authenticated MCP tool groups."""

from typing import Any
from langboard_shared.domain.models import Bot, User
from langboard_shared.domain.services import DomainService
from ..mcp_integration import McpRoleFilter, McpTool
from ..mcp_tools.RoleChecker import McpRoleChecker
from ..middlewares.McpAuthMiddleware import mcp_auth_context


def _permission_state(actor: User | Bot, handler: Any, arguments: dict[str, Any]) -> str:
    """Classify a read-only capability check without making the capability tool role-filtered."""

    if not McpRoleFilter.exists(handler):
        return "allowed"
    service = DomainService()
    try:
        allowed = McpRoleChecker(service).check_permission(handler, actor, arguments)
    finally:
        service.close()
    return "allowed" if allowed else "denied"


@McpTool.add(
    "user",
    description=(
        "Inspect the active tool group, schema/runtime contract, and action permissions "
        "before invoking write tools. Supply project_uid when possible for concrete card permissions."
    ),
)
def diagnose_connection(
    user: User,
    project_uid: str | None = None,
    card_uid: str | None = None,
) -> dict:
    """Return non-secret connection and capability state for the current MCP session."""

    actor_arguments = {"project_uid": project_uid, "card_uid": card_uid}
    tools: list[dict[str, Any]] = []

    auth_data = mcp_auth_context.get()
    tool_group = auth_data.get("tool_group") if auth_data else None
    if tool_group is None or tool_group.activated_at is None:
        raise ValueError("An active MCP tool group is required")

    allowed_names = set(tool_group.tools)
    for name, tool_data in sorted(McpTool.get_tools().items()):
        if name not in allowed_names:
            continue

        required = list(tool_data["input_schema"].get("required", []))
        if "project_uid" in required and not project_uid:
            permission = "unknown_project_scope"
        else:
            permission = _permission_state(user, tool_data["handler"], actor_arguments)

        tools.append(
            {
                "name": name,
                "accessible_type": tool_data["accessible_type"],
                "required_fields": required,
                "permission": permission,
            }
        )

    return {
        "authenticated": True,
        "identity": {"actor_type": type(user).__name__},
        "tool_group": {"active": True, "tool_count": len(tools)},
        "scope": {
            "project_uid_present": project_uid is not None,
            "card_uid_present": card_uid is not None,
        },
        "schema_runtime": {
            "mismatched_tools": [],
            "source": "registered_metadata",
        },
        "tools": tools,
    }
