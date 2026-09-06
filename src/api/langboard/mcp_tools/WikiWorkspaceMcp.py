"""Bounded, user-authorized wiki MCP queries and append commands."""

from typing import Any, Literal
from fastmcp.exceptions import ValidationError
from langboard_shared.core.db import EditorContentModel
from langboard_shared.core.exceptions.WikiContentConflict import WikiContentConflict
from langboard_shared.domain.models import ProjectRole, User
from langboard_shared.domain.models.ProjectRole import ProjectRoleAction
from langboard_shared.domain.services import DomainService
from langboard_shared.security import RoleFinder
from ..mcp_integration import McpRoleFilter, McpTool
from ..wiki_workspace.application import append_wiki, read_wiki
from ..wiki_workspace.domain import WikiValidationError
from ..wiki_workspace.infrastructure import NativeWikiRepository


@McpTool.add(
    "user", description="List or literal-search readable project wikis, excluding private inaccessible content."
)
@McpRoleFilter.add(ProjectRole, [ProjectRoleAction.Read], RoleFinder.project)
def list_project_wikis(
    project_uid: str, user: User, service: DomainService, query: str = "", cursor: str | None = None, limit: int = 20
) -> dict[str, Any]:
    """Return bounded titles and optional match snippets; cursor is next_cursor from the previous page."""
    return NativeWikiRepository(user, service).list_wikis(project_uid, query, cursor, limit)


@McpTool.add("user", description="Read exact wiki content page-by-page without changing content or read state.")
@McpRoleFilter.add(ProjectRole, [ProjectRoleAction.Read], RoleFinder.project)
def read_wiki_content(
    project_uid: str, wiki_uid: str, user: User, service: DomainService, cursor: str | None = None, limit: int = 8000
) -> dict[str, Any]:
    """Return a revision-bound exact Markdown page; restart if the wiki changes."""
    try:
        return read_wiki(NativeWikiRepository(user, service), project_uid, wiki_uid, cursor, limit)
    except ValueError as exc:
        raise ValidationError(str(exc)) from exc


@McpTool.add("user", description="List stored wiki revision activities under current wiki permissions.")
@McpRoleFilter.add(ProjectRole, [ProjectRoleAction.Read], RoleFinder.project)
def list_wiki_revisions(
    project_uid: str, wiki_uid: str, user: User, service: DomainService, cursor: str | None = None, limit: int = 20
) -> dict[str, Any]:
    """Return revision IDs and available content sides, not entire revision bodies."""
    return NativeWikiRepository(user, service).revisions(project_uid, wiki_uid, cursor, limit)


@McpTool.add("user", description="Read one stored before/after wiki revision as exact, bounded content pages.")
@McpRoleFilter.add(ProjectRole, [ProjectRoleAction.Read], RoleFinder.project)
def read_wiki_revision(
    project_uid: str,
    wiki_uid: str,
    revision_uid: str,
    user: User,
    service: DomainService,
    side: Literal["before", "after"] = "after",
    cursor: str | None = None,
    limit: int = 8000,
) -> dict[str, Any]:
    """Historical content is subject to the wiki's current access permission."""
    return NativeWikiRepository(user, service).revision_page(project_uid, wiki_uid, revision_uid, side, cursor, limit)


@McpTool.add(
    "user", description="Append reviewed Markdown to a wiki, preserving existing text and rejecting stale revisions."
)
@McpRoleFilter.add(ProjectRole, [ProjectRoleAction.Read], RoleFinder.project)
def append_wiki_content(
    project_uid: str, wiki_uid: str, expected_revision: str, text: str, user: User, service: DomainService
) -> dict[str, str]:
    """Never truncate the existing wiki or archive a card implicitly."""
    try:
        return append_wiki(NativeWikiRepository(user, service), project_uid, wiki_uid, expected_revision, text)
    except (WikiContentConflict, WikiValidationError) as exc:
        raise ValidationError(str(exc)) from exc


@McpTool.add("user", description="Create a new project-visible wiki with reviewed title and Markdown content.")
@McpRoleFilter.add(ProjectRole, [ProjectRoleAction.Read], RoleFinder.project)
def create_project_wiki(
    project_uid: str, title: str, content: str, user: User, service: DomainService
) -> dict[str, str]:
    """Use the native wiki creation path and existing activity history."""
    if not title.strip() or len(title) > 300 or len(content) > 32000:
        raise ValidationError("title must be 1..300 characters and content at most 32000")
    result = service.project_wiki.create(user, project_uid, title, EditorContentModel(content=content))
    if result is None:
        raise ValidationError("Project not found")
    wiki, _ = result
    return {"wiki_uid": wiki.get_uid(), "title": wiki.title, "visibility": "project"}
