"""Native wiki read views share canonical queries and current authorization."""

from typing import Annotated, Any, Literal
from langboard_shared.domain.models import ProjectRole
from langboard_shared.domain.models.ProjectRole import ProjectRoleAction
from langboard_shared.security import RoleFinder
from pydantic import Field
from ..mcp_integration import McpRoleFilter, McpTool


@McpTool.add(
    "user",
    description="Read exact wiki content, revision history, or a stored revision. Follow returned cursors. History limit is at most 50; revision_uid/side require revision view.",
)
@McpRoleFilter.add(ProjectRole, [ProjectRoleAction.Read], RoleFinder.project)
async def read_wiki(
    project_uid: str,
    wiki_uid: str,
    view: Literal["content", "history", "revision"] = "content",
    revision_uid: str | None = None,
    side: Literal["before", "after"] | None = None,
    cursor: str | None = None,
    limit: Annotated[int, Field(ge=1, le=16000, strict=True)] | None = None,
) -> dict[str, Any]:
    from ..mcp_integration.Server import McpServer

    if view != "revision" and (revision_uid is not None or side is not None):
        raise ValueError("revision_uid and side require revision view")
    if view == "revision" and (not revision_uid or not revision_uid.strip()):
        raise ValueError("Select a revision returned by history view")
    if view == "history" and limit is not None and limit > 50:
        raise ValueError("History limit must be at most 50")
    command = {
        "content": "read_wiki_content",
        "history": "list_wiki_revisions",
        "revision": "read_wiki_revision",
    }[view]
    arguments = {
        "project_uid": project_uid,
        "wiki_uid": wiki_uid,
        "cursor": cursor,
        "limit": limit if limit is not None else (20 if view == "history" else 8000),
    }
    if view == "revision":
        arguments.update(revision_uid=revision_uid, side=side or "after")
    metadata = McpTool.get_tool(command)
    if metadata is None:
        raise RuntimeError("Native wiki query is unavailable")
    return await McpServer._wrap_tool(command, metadata["handler"])(**arguments)
