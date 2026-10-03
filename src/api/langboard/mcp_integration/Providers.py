"""FastMCP provider adapter for the existing native domain registry."""

from collections.abc import Callable
from typing import Any
from fastmcp.prompts import Prompt
from fastmcp.resources import Resource
from fastmcp.server.providers.local_provider import LocalProvider
from fastmcp.tools import Tool
from .Tool import McpTool


def create_compatibility_provider(wrap_tool: Callable[[str, Callable[..., Any]], Callable[..., Any]]) -> LocalProvider:
    """Preserve legacy names and domain wrappers while using native providers."""
    provider = LocalProvider(on_duplicate="error")
    for name, metadata in McpTool.get_tools().items():
        provider.add_tool(
            Tool.from_function(wrap_tool(name, metadata["handler"]), name=name, description=metadata["description"])
        )
    provider.add_resource(Resource.from_function(_workflow_policy, uri="langboard://policy/workflow", name="workflow_policy"))
    provider.add_prompt(Prompt.from_function(_workflow_policy_prompt, name="apply_workflow_policy"))
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
