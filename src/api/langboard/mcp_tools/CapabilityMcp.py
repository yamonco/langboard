"""Runtime capability diagnostics for native OAuth and legacy MCP sessions."""

from typing import Any
from langboard_shared.domain.models import Bot, User
from langboard_shared.domain.services import DomainService
from ..mcp_integration import McpRoleFilter, McpTool
from ..mcp_tools.RoleChecker import McpRoleChecker
from ..middlewares.McpAuthMiddleware import mcp_auth_context


def _scoped_permission(actor, metadata, arguments):
    required = list(metadata["input_schema"].get("required", []))
    if "project_uid" in required and not arguments.get("project_uid"):
        return "unknown_project_scope"
    if "card_uid" in required and not arguments.get("card_uid"):
        return "unknown_card_scope"
    return _permission_state(actor, metadata["handler"], arguments)


def _action_permissions(actor, name, registered, arguments):
    """Report canonical action permissions rather than only the facade envelope."""
    from .CardActionsMcp import CARD_ACTION_COMMANDS
    from .ChecklistActionsMcp import CHECKLIST_ACTION_COMMANDS
    from .CommentActionsMcp import COMMENT_ACTION_COMMANDS

    commands = {
        "update_card": CARD_ACTION_COMMANDS,
        "change_card_checklist": CHECKLIST_ACTION_COMMANDS,
        "change_card_comment": COMMENT_ACTION_COMMANDS,
    }.get(name)
    if commands is None:
        return None
    return {
        action: _scoped_permission(actor, registered[command], arguments) if command in registered else "unavailable"
        for action, command in commands.items()
    }


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
    native_oauth = bool(auth_data and auth_data.get("transport") == "oauth")
    if not native_oauth and (tool_group is None or tool_group.activated_at is None):
        raise ValueError("An active MCP tool group is required")

    registered = McpTool.get_tools()
    allowed_names = set(registered) if native_oauth else set(tool_group.tools)
    for name, tool_data in sorted(registered.items()):
        if name not in allowed_names:
            continue
        if tool_data["accessible_type"] == "bot":
            continue

        required = list(tool_data["input_schema"].get("required", []))
        permission = _scoped_permission(user, tool_data, actor_arguments)

        entry = {
            "name": name,
            "accessible_type": tool_data["accessible_type"],
            "required_fields": required,
            "permission": permission,
        }
        if native_oauth:
            actions = _action_permissions(user, name, registered, actor_arguments)
            if actions is not None:
                entry["actions"] = actions
                entry["permission"] = "action_dependent"
        tools.append(entry)

    return {
        "authenticated": True,
        "identity": {"actor_type": type(user).__name__},
        "tool_group": {"active": not native_oauth, "tool_count": len(tools)},
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
