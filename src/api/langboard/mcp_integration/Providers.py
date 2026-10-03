"""FastMCP provider adapter for the existing native domain registry."""

import json
from collections.abc import Callable
from typing import Any
from fastmcp.exceptions import AuthorizationError
from fastmcp.prompts import Prompt
from fastmcp.resources import Resource, ResourceTemplate
from fastmcp.server.providers.local_provider import LocalProvider
from fastmcp.tools import Tool
from .Tool import McpTool
from .ToolGroupMiddleware import ToolGroupMiddleware


def create_compatibility_provider(wrap_tool: Callable[[str, Callable[..., Any]], Callable[..., Any]]) -> LocalProvider:
    """Preserve legacy names and domain wrappers while using native providers."""
    provider = LocalProvider(on_duplicate="error")
    for name, metadata in McpTool.get_tools().items():
        provider.add_tool(
            Tool.from_function(wrap_tool(name, metadata["handler"]), name=name, description=metadata["description"])
        )
    provider.add_resource(Resource.from_function(_workflow_policy, uri="langboard://policy/workflow", name="workflow_policy"))
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
