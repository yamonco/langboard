"""Native authorized wiki storage, bounded searches and existing activity snapshots."""

from typing import Any
from fastmcp.exceptions import AuthorizationError
from langboard_shared.core.db import DbSession, EditorContentModel, SqlBuilder
from langboard_shared.core.db.DbEngine import DbEngine
from langboard_shared.domain.models import ProjectWiki, ProjectWikiActivity, ProjectWikiAssignedUser, User
from langboard_shared.domain.services import DomainService
from langboard_shared.helpers import InfraHelper
from sqlalchemy import JSON, cast, func, or_, select
from .domain import WikiRepository, WikiSnapshot, content_page


class NativeWikiRepository(WikiRepository):
    """Reuse native wiki permission, content and history semantics."""

    def __init__(self, user: User, service: DomainService) -> None:
        self.user = user
        self.service = service

    def _wiki(self, project_uid: str, wiki_uid: str) -> ProjectWiki:
        project = self.service.project.get_by_id_like(project_uid)
        wiki = self.service.project_wiki.get_by_id_like(wiki_uid)
        if project is None or wiki is None or wiki.project_id != project.id:
            raise ValueError("Wiki not found in project")
        if self.service.project_wiki.convert_to_api_response(self.user, project, wiki)["forbidden"]:
            raise AuthorizationError("This wiki is private and not assigned to the current user")
        return wiki

    def snapshot(self, project_uid: str, wiki_uid: str) -> WikiSnapshot:
        """Check current per-wiki visibility before returning exact Markdown."""
        wiki = self._wiki(project_uid, wiki_uid)
        return WikiSnapshot(wiki.get_uid(), wiki.title, wiki.content.content)

    def append(self, project_uid: str, wiki_uid: str, before: str, after: str) -> None:
        """Use native events/history and a locked content-only conditional save."""
        wiki = self._wiki(project_uid, wiki_uid)
        if not self.service.project_wiki.is_assigned(self.user, wiki):
            raise AuthorizationError("Current user cannot edit this private wiki")
        result = self.service.project_wiki.update(
            self.user, project_uid, wiki, {"content": EditorContentModel(content=after)}, expected_content=before
        )
        if result is None:
            raise ValueError("Wiki not found")

    def list_wikis(self, project_uid: str, query: str, after_uid: str | None, limit: int) -> dict[str, Any]:
        """Filter permissions in SQL before literal search, paging or snippets."""
        if not 1 <= limit <= 50 or len(query) > 1000:
            raise ValueError("limit must be 1..50 and query at most 1000 characters")
        project = self.service.project.get_by_id_like(project_uid)
        if project is None:
            raise ValueError("Project not found")
        columns = [ProjectWiki.column("id"), ProjectWiki.column("title"), ProjectWiki.column("is_public")]
        if query:
            columns.append(ProjectWiki.column("content"))
        statement = SqlBuilder.select.columns(*columns).where(
            (ProjectWiki.column("project_id") == project.id) & ProjectWiki.column("deleted_at").is_(None)
        )
        if not self.user.is_admin and project.owner_id != self.user.id:
            assigned = select(ProjectWikiAssignedUser.project_wiki_id).where(
                ProjectWikiAssignedUser.user_id == self.user.id
            )
            statement = statement.where(
                or_(ProjectWiki.column("is_public").is_(True), ProjectWiki.column("id").in_(assigned))
            )
        if after_uid:
            statement = statement.where(ProjectWiki.column("id") > InfraHelper.convert_id(after_uid))
        if query:
            # Native ModelColumnType stores a JSON string containing the model JSON.
            # Decode that wrapper before searching; do not search escaped serialization.
            content_column = ProjectWiki.column("content")
            if DbEngine.get_readonly_engine().dialect.name == "sqlite":
                content_text = func.json_extract(func.json_extract(content_column, "$"), "$.content")
            else:
                content_text = cast(cast(content_column, JSON)[()].as_string(), JSON)["content"].as_string()
            statement = statement.where(
                or_(
                    ProjectWiki.column("title").contains(query, autoescape=True),
                    content_text.contains(query, autoescape=True),
                )
            )
        with DbSession.use(readonly=True) as db:
            rows = db.exec(statement.order_by(ProjectWiki.column("id").asc()).limit(limit + 1)).all()
        items = []
        for row in rows[:limit]:
            item = {"wiki_uid": row[0].to_short_code(), "title": row[1], "is_public": row[2]}
            if query:
                text = row[3].content
                index = text.find(query)
                start = max(0, index - 100)
                item.update(
                    {"snippet": text[start : start + 300], "snippet_offset": start, "content_match": index >= 0}
                )
            items.append(item)
        return {
            "items": items,
            "next_cursor": items[-1]["wiki_uid"] if len(rows) > limit else None,
            "query": query,
            "search_mode": "literal",
            "limit": limit,
        }

    def revisions(self, project_uid: str, wiki_uid: str, before_uid: str | None, limit: int) -> dict[str, Any]:
        """List existing audit revisions without emitting unbounded body snapshots."""
        wiki = self._wiki(project_uid, wiki_uid)
        if not 1 <= limit <= 50:
            raise ValueError("limit must be 1..50")
        changes = ProjectWikiActivity.column("activity_history")["changes"]
        statement = SqlBuilder.select.columns(
            ProjectWikiActivity.column("id"),
            ProjectWikiActivity.column("created_at"),
            ProjectWikiActivity.column("activity_type"),
            changes["before"]["content"].as_string().is_not(None),
            changes["after"]["content"].as_string().is_not(None),
        ).where(
            (ProjectWikiActivity.column("project_id") == wiki.project_id)
            & (ProjectWikiActivity.column("project_wiki_id") == wiki.id)
        )
        if before_uid:
            statement = statement.where(ProjectWikiActivity.column("id") < InfraHelper.convert_id(before_uid))
        with DbSession.use(readonly=True) as db:
            rows = db.exec(statement.order_by(ProjectWikiActivity.column("id").desc()).limit(limit + 1)).all()
        items = []
        for revision_id, created_at, activity_type, has_before, has_after in rows[:limit]:
            items.append(
                {
                    "revision_uid": revision_id.to_short_code(),
                    "created_at": created_at,
                    "activity_type": activity_type.value,
                    "content_sides": [
                        side for side, present in (("before", has_before), ("after", has_after)) if present
                    ],
                }
            )
        return {
            "items": items,
            "next_cursor": items[-1]["revision_uid"] if len(rows) > limit else None,
            "history_source": "native_activity_log",
            "history_may_be_pending": True,
        }

    def revision_page(
        self, project_uid: str, wiki_uid: str, revision_uid: str, side: str, cursor: str | None, limit: int
    ) -> dict[str, Any]:
        """Reauthorize the current wiki before reading an old content snapshot."""
        wiki = self._wiki(project_uid, wiki_uid)
        if side not in ("before", "after"):
            raise ValueError("side must be before or after")
        activity = InfraHelper.get_by_id_like(ProjectWikiActivity, revision_uid)
        if activity is None or activity.project_id != wiki.project_id or activity.project_wiki_id != wiki.id:
            raise ValueError("Revision not found in this wiki")
        content = activity.activity_history.get("changes", {}).get(side, {}).get("content")
        if not isinstance(content, dict) or not isinstance(content.get("content"), str):
            raise ValueError("This activity has no stored content snapshot; do not infer a historical body")
        snapshot = WikiSnapshot(wiki_uid, wiki.title, content["content"])
        return {
            **content_page(snapshot, f"{project_uid}/{wiki_uid}/{revision_uid}/{side}", cursor, limit),
            "revision_uid": revision_uid,
            "side": side,
            "title_source": "current_wiki",
        }
