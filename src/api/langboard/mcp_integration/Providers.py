"""FastMCP provider adapter for the existing native domain registry."""

import json
from collections.abc import Callable
from typing import Any
from fastmcp.exceptions import AuthorizationError
from fastmcp.prompts import Prompt
from fastmcp.resources import Resource, ResourceTemplate
from fastmcp.server.providers.local_provider import LocalProvider
from fastmcp.server.transforms import Visibility
from fastmcp.tools import Tool
from .Annotations import tool_annotations
from .BoardOutputs import BOARD_OUTPUTS
from .BotOutputs import BOT_OUTPUTS
from .ContentOutputs import CONTENT_OUTPUTS
from .Outputs import with_typed_output
from .Tool import McpTool
from .ToolGroupMiddleware import ToolGroupMiddleware
from .WorkOutputs import WORK_OUTPUTS


# Existing canonical entry points; profile selection never grants permission.
AGENT_CORE_TOOLS = frozenset(
    {
        "diagnose_connection",
        "get_projects",
        "get_project_identity",
        "create_project",
        "list_project_cards",
        "search_project_cards",
        "get_card_bundle",
        "create_card",
        "patch_card_description",
        "assign_card_to_me",
        "apply_card_graph_patch",
        "record_card_verification_evidence",
        "change_card_checkitem_work",
        "list_my_work",
        "list_project_members",
        "search_project_people",
        "add_project_people",
        "list_project_wikis",
        "read_wiki_content",
        "patch_wiki_content",
        "create_project_wiki",
        "get_unread_notifications",
        "mark_notification_read",
        "read_card_attachment",
        "get_project_label_catalog",
        "get_shared_user_activities",
        "update_card_comment",
        "create_card_checklist",
        "create_card_checkitem",
        "update_card_checkitem",
    }
)


def create_native_domain_provider(
    wrap_tool: Callable[[str, Callable[..., Any]], Callable[..., Any]],
    *,
    modern_annotations: bool = False,
) -> LocalProvider:
    """Adapt the native registry once; every profile uses identical domain wrappers."""
    provider = LocalProvider(on_duplicate="error")
    for name, metadata in McpTool.get_tools().items():
        handler = wrap_tool(name, metadata["handler"])
        if modern_annotations:
            handler = with_typed_output(
                name,
                handler,
                WORK_OUTPUTS.get(name) or CONTENT_OUTPUTS.get(name) or BOT_OUTPUTS.get(name) or BOARD_OUTPUTS.get(name),
            )
        provider.add_tool(
            Tool.from_function(
                handler,
                name=name,
                description=metadata["description"],
                annotations=tool_annotations(name) if modern_annotations else None,
            )
        )
    provider.add_resource(
        Resource.from_function(_workflow_policy, uri="langboard://policy/workflow", name="workflow_policy")
    )
    provider.add_prompt(Prompt.from_function(_workflow_policy_prompt, name="apply_workflow_policy"))
    metadata = McpTool.get_tool("get_card_bundle")
    if metadata:
        read_bundle = wrap_tool("get_card_bundle", metadata["handler"])

        async def card_workflow(project_uid: str, card_uid: str) -> str:
            """Read current card workflow using the same grants and domain query as the tool."""
            if "get_card_bundle" not in ToolGroupMiddleware._allowed_tools():
                raise AuthorizationError("get_card_bundle is not allowed")
            result = await read_bundle(project_uid=project_uid, card_uid=card_uid, include=[])
            data = result.model_dump(mode="json") if hasattr(result, "model_dump") else result
            card = data.get("card")
            if not card:
                raise ValueError("Card not found")
            return json.dumps(
                {"workflow": card.get("workflow"), "work_state": card.get("work_state")},
                ensure_ascii=False,
            )

        provider.add_resource(
            ResourceTemplate.from_function(
                card_workflow,
                uri_template="langboard://projects/{project_uid}/cards/{card_uid}/workflow",
                name="card_workflow",
                mime_type="application/json",
            )
        )

        async def apply_card_workflow(project_uid: str, card_uid: str) -> str:
            """Apply current server workflow and work state without changing the card."""
            return _workflow_policy() + "\nCurrent server state:\n" + await card_workflow(project_uid, card_uid)

        provider.add_prompt(Prompt.from_function(apply_card_workflow, name="apply_card_workflow"))
    return provider


def create_compatibility_provider(wrap_tool: Callable[[str, Callable[..., Any]], Callable[..., Any]]) -> LocalProvider:
    """Preserve the complete legacy catalog without visibility changes."""
    return create_native_domain_provider(wrap_tool)


def create_agent_core_provider(wrap_tool: Callable[[str, Callable[..., Any]], Callable[..., Any]]) -> LocalProvider:
    """Expose canonical entry points using FastMCP's native visibility transform."""
    provider = create_native_domain_provider(wrap_tool, modern_annotations=True)
    provider.add_transform(Visibility(False, components={"tool"}, match_all=True))
    provider.add_transform(Visibility(True, names=set(AGENT_CORE_TOOLS), components={"tool"}))
    return provider


def create_raw_primitive_provider(wrap_tool: Callable[[str, Callable[..., Any]], Callable[..., Any]]) -> LocalProvider:
    """Keep primitive and compatibility actions outside the compact core catalog."""
    provider = create_native_domain_provider(wrap_tool, modern_annotations=True)
    provider.add_transform(Visibility(False, names=set(AGENT_CORE_TOOLS), components={"tool"}))
    return provider


def _workflow_policy() -> str:
    """Return server-owned workflow policy shared by MCP clients."""
    return (
        "Langboard workflow policy\n"
        "1. Treat server workflow_stage, column_description, workflow_stage_description, "
        "workflow_guidance, and workflow_stage_status as authoritative.\n"
        "2. For a project, read get_project_identity before choosing a column or stage.\n"
        "3. For a card, read get_card_bundle workflow and work_state before claiming, moving, "
        "completing, or reporting readiness.\n"
        "4. Preserve review, verification, dependency, and blocker gates; checklist progress "
        "does not prove approval.\n"
        "5. Never infer a workflow stage from a localized column name or client defaults."
    )


def _workflow_policy_prompt() -> str:
    """Tell an agent how to apply the server-owned workflow policy."""
    return _workflow_policy()
