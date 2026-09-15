"""Governed project-search MCP tool."""

from datetime import datetime
from typing import Literal
from langboard_shared.core.types import SafeDateTime
from langboard_shared.domain.models import ProjectRole
from langboard_shared.domain.models.ProjectRole import ProjectRoleAction
from langboard_shared.domain.services import DomainService
from langboard_shared.security import RoleFinder
from ..mcp_integration import McpRoleFilter, McpTool


@McpTool.add(description="Search cards inside one readable project without changing view or read state.")
@McpRoleFilter.add(ProjectRole, [ProjectRoleAction.Read], RoleFinder.project)
def search_project_cards(
    project_uid: str,
    query: str,
    service: DomainService,
    date_field: Literal["created_at", "updated_at"] = "updated_at",
    since: str | None = None,
    until: str | None = None,
) -> dict:
    """Search bounded card context through the native project-scoped query."""

    normalized_query = query.strip()
    if not 1 <= len(normalized_query) <= 1000:
        raise ValueError("query must contain between 1 and 1000 characters")

    def parse_bound(value: str | None) -> SafeDateTime | None:
        if value is None:
            return None
        parsed = datetime.fromisoformat(value)
        if parsed.utcoffset() is None:
            raise ValueError("Date bounds must include a timezone")
        return SafeDateTime.fromisoformat(value)

    lower, upper = parse_bound(since), parse_bound(until)
    if lower is not None and upper is not None and lower >= upper:
        raise ValueError("since must be earlier than until")
    return {
        "cards": service.card.search_context_by_project(
            project_uid,
            normalized_query,
            date_field=date_field,
            since=lower,
            until=upper,
        )
    }
