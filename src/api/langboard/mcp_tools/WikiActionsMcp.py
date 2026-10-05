"""Native wiki read views share canonical queries and current authorization."""

from typing import Annotated, Any, Literal
from langboard_shared.domain.models import ProjectRole
from langboard_shared.domain.models.ProjectRole import ProjectRoleAction
from langboard_shared.security import RoleFinder
from pydantic import BaseModel, ConfigDict, Field, model_serializer, model_validator
from ..mcp_integration import McpRoleFilter, McpTool
from ..mcp_integration.Outputs import CommandOutput, DeletedOutput, WikiRevisionOutput
from .WikiMcp import WikiTextEdit


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


# Body whitespace is content; do not normalize it at the facade boundary.
class WikiChange(BaseModel):
    model_config = ConfigDict(extra="forbid")


class AppendWiki(WikiChange):
    action: Literal["append"]
    text: Annotated[str, Field(min_length=1, max_length=32000)]


class PatchWiki(WikiChange):
    action: Literal["patch"]
    edits: Annotated[list[WikiTextEdit], Field(min_length=1, max_length=20)]


class ReplaceWiki(WikiChange):
    action: Literal["replace"]
    content: Annotated[str, Field(max_length=32000)]


class DeleteWiki(WikiChange):
    action: Literal["delete"]


WikiMutation = Annotated[AppendWiki | PatchWiki | ReplaceWiki | DeleteWiki, Field(discriminator="action")]
WIKI_ACTION_COMMANDS = {
    "append": "append_wiki_content",
    "patch": "patch_wiki_content",
    "replace": "replace_wiki_content",
    "delete": "delete_project_wiki",
}


class WikiActionOutput(CommandOutput):
    wiki_uid: str | None = None
    revision: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")] | None = None
    deleted: Literal[True] | None = None

    @model_validator(mode="after")
    def require_one_result(self):
        changed = self.wiki_uid is not None and self.revision is not None and self.deleted is None
        deleted = self.deleted is True and self.wiki_uid is None and self.revision is None
        if not (changed or deleted):
            raise ValueError("Expected one wiki mutation result")
        return self

    @model_serializer(mode="wrap")
    def serialize_result(self, handler):
        return {key: value for key, value in handler(self).items() if value is not None}


@McpTool.add(
    "user",
    description="Append, patch, replace, or delete one revision-reviewed wiki with an action-specific change. Preserve content; deletion requires explicit user intent.",
)
@McpRoleFilter.add(ProjectRole, [ProjectRoleAction.Read], RoleFinder.project)
async def update_wiki(
    project_uid: str,
    wiki_uid: str,
    expected_revision: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")],
    change: WikiMutation,
) -> WikiActionOutput:
    from ..mcp_integration.Server import McpServer

    command = WIKI_ACTION_COMMANDS[change.action]
    metadata = McpTool.get_tool(command)
    if metadata is None:
        raise RuntimeError("Native wiki command is unavailable")
    result = await McpServer._wrap_tool(command, metadata["handler"])(
        project_uid=project_uid,
        wiki_uid=wiki_uid,
        expected_revision=expected_revision,
        **change.model_dump(exclude={"action"}),
    )
    output = DeletedOutput if change.action == "delete" else WikiRevisionOutput
    return WikiActionOutput.model_validate(output.model_validate(result).model_dump())
