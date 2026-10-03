"""Standard hints for modern profiles; authorization remains independent."""

from fastmcp.server.transforms import Transform
from mcp_types import ToolAnnotations


class ToolAnnotationTransform(Transform):
    """Attach hints to synthetic tools without altering their call handlers."""

    async def list_tools(self, tools):
        return [tool.model_copy(update={"annotations": tool_annotations(tool.name)}) for tool in tools]

    async def get_tool(self, name, call_next, *, version=None):
        tool = await call_next(name, version=version)
        return tool.model_copy(update={"annotations": tool_annotations(tool.name)}) if tool is not None else None


# Reviewed query entry points. Do not infer read-only behavior from a name prefix.
READ_ONLY_TOOLS = frozenset(
    {
        "diagnose_connection",
        "get_projects",
        "get_starred_projects",
        "get_project_identity",
        "list_project_cards",
        "search_project_cards",
        "get_card_bundle",
        "list_my_work",
        "list_project_members",
        "get_project_assigned_users",
        "get_project_columns",
        "get_project_labels",
        "get_project_label_catalog",
        "get_project_checklists",
        "get_global_relationships",
        "get_card",
        "get_card_attachments",
        "read_card_attachment",
        "get_card_linked_wikis",
        "get_public_card_metadata",
        "get_public_card_metadata_by_key",
        "get_card_metadata",
        "get_card_metadata_by_key",
        "get_wiki_metadata",
        "get_wiki_metadata_by_key",
        "list_project_wikis",
        "read_wiki_content",
        "list_wiki_revisions",
        "read_wiki_revision",
        "get_unread_notifications",
        "get_shared_user_activities",
        "search_project_people",
        "get_project_activities",
        "get_card_activities",
        "get_wiki_activities",
        "get_project_column_activities",
        "get_current_user_activities",
        "get_my_work_cards",
        "is_project_available",
        "is_project_assignee",
        "get_project_bot_scopes",
        "get_card_bot_scopes",
        "get_column_bot_scopes",
        "get_bot_schedules_by_project",
        "get_bot_schedules_by_card",
        "get_bot_schedules_by_column",
        "get_column_bot_schedules",
        "get_bot_hook",
        "search_raw_tools",
    }
)


def tool_annotations(name: str) -> ToolAnnotations:
    """Keep unreviewed operations and the generic Raw proxy conservative."""
    read_only = name in READ_ONLY_TOOLS
    return ToolAnnotations(
        read_only_hint=read_only,
        destructive_hint=not read_only,
        idempotent_hint=read_only,
        open_world_hint=True,
    )
