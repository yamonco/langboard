"""Kanboard → Langboard entity mapping: projects, columns, cards, comments.

Converts Kanboard export entities into Langboard import payloads with
full field mapping including columns, swimlanes, and comment threads.
"""

from dataclasses import dataclass, field
from typing import Any
from .kanboard_schema import (
    KanboardImportResult,
    normalize_column_name,
)


@dataclass
class KanboardProjectImport:
    """A single Kanboard project mapped for Langboard import."""

    source_project_id: str
    title: str
    description: str = ""
    columns: list[dict[str, Any]] = field(default_factory=list)
    cards: list[dict[str, Any]] = field(default_factory=list)
    comments: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class KanboardFullImportResult:
    """Result of mapping a complete Kanboard export."""

    projects: list[KanboardProjectImport] = field(default_factory=list)
    total_projects: int = 0
    total_cards: int = 0
    total_comments: int = 0
    total_columns: int = 0
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def map_kanboard_comment(comment: dict[str, Any]) -> dict[str, Any] | None:
    """Map a Kanboard comment to a Langboard comment payload."""
    if not comment.get("id") or not comment.get("comment"):
        return None

    from datetime import datetime, timezone

    mapped: dict[str, Any] = {
        "source_id": str(comment["id"]),
        "content": comment["comment"],
        "source_task_id": str(comment.get("task_id", "")),
        "source_user_id": comment.get("user_id", ""),
        "source_username": comment.get("username", ""),
    }

    date_val = comment.get("date_creation", 0)
    if date_val:
        try:
            ts = int(date_val)
            if ts > 0:
                mapped["created_at"] = datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()
        except (ValueError, TypeError):
            pass

    return mapped


def map_kanboard_project(
    project: dict[str, Any],
    tasks: list[dict[str, Any]],
    comments: list[dict[str, Any]],
) -> KanboardProjectImport:
    """Map a Kanboard project with its tasks and comments."""
    project_id = str(project.get("id", ""))
    title = project.get("name", f"Imported Project {project_id}")

    # Extract unique columns from this project's tasks only
    project_tasks = [t for t in tasks if str(t.get("project_id", "")) == project_id]
    column_names: list[str] = []
    for task in project_tasks:
        col = task.get("column_name", "")
        normalized = normalize_column_name(col) if col else "Backlog"
        if normalized not in column_names:
            column_names.append(normalized)

    if not column_names:
        column_names = ["Backlog", "Ready", "In Progress", "Review", "Done"]

    columns = [{"name": col, "description": ""} for col in sorted(column_names)]

    # Map tasks
    card_result = _map_tasks(project_tasks)

    # Map comments (filter to this project's tasks)
    task_ids = {str(t.get("id", "")) for t in project_tasks}
    mapped_comments = []
    for c in comments:
        if str(c.get("task_id", "")) in task_ids:
            mapped = map_kanboard_comment(c)
            if mapped:
                mapped_comments.append(mapped)

    return KanboardProjectImport(
        source_project_id=project_id,
        title=title,
        description=project.get("description", ""),
        columns=columns,
        cards=card_result.mapped_cards,
        comments=mapped_comments,
    )


def _map_tasks(tasks: list[dict[str, Any]]) -> KanboardImportResult:
    """Map a list of Kanboard tasks."""
    from .kanboard_schema import map_kanboard_export
    return map_kanboard_export(tasks)


def map_full_kanboard_export(
    projects: list[dict[str, Any]],
    tasks: list[dict[str, Any]],
    comments: list[dict[str, Any]],
) -> KanboardFullImportResult:
    """Map a complete Kanboard export (projects + tasks + comments)."""
    result = KanboardFullImportResult()

    for project in projects:
        if not project.get("id"):
            result.errors.append(f"Project missing id: {project.get('name', '?')}")
            continue

        try:
            mapped = map_kanboard_project(project, tasks, comments)
            result.projects.append(mapped)
            result.total_projects += 1
            result.total_cards += len(mapped.cards)
            result.total_comments += len(mapped.comments)
            result.total_columns += len(mapped.columns)
        except Exception as exc:
            result.errors.append(f"Project {project.get('id')}: {str(exc)[:60]}")

    return result
