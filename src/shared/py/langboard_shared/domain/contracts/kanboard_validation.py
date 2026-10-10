"""Kanboard import validation: field checks, orphan detection, dry-run report."""

from dataclasses import dataclass, field
from typing import Any
from .kanboard_import import map_full_kanboard_export


@dataclass
class ValidationIssue:
    """A single validation finding."""

    severity: str  # "error" | "warning" | "info"
    entity: str  # "project" | "card" | "comment" | "column"
    source_id: str
    message: str


@dataclass
class ValidationReport:
    """Complete dry-run validation report."""

    is_valid: bool = True
    total_issues: int = 0
    errors: int = 0
    warnings: int = 0
    infos: int = 0
    issues: list[ValidationIssue] = field(default_factory=list)
    summary: str = ""

    @property
    def can_import(self) -> bool:
        return self.errors == 0


def validate_kanboard_export(
    projects: list[dict[str, Any]],
    tasks: list[dict[str, Any]],
    comments: list[dict[str, Any]],
) -> ValidationReport:
    """Validate a Kanboard export before import.

    Checks: required fields, duplicate IDs, orphan references,
    date validity, column coverage, and data truncation risks.
    """
    report = ValidationReport()
    issue = _add_issue(report)

    # 1. Validate projects
    project_ids = set()
    for p in projects:
        pid = str(p.get("id", ""))
        if not pid:
            issue("error", "project", "?", "Project has no ID")
            continue
        if pid in project_ids:
            issue("warning", "project", pid, "Duplicate project ID")
            continue
        project_ids.add(pid)

        if not p.get("name", "").strip():
            issue("warning", "project", pid, "Project has no name")

    # 2. Validate tasks
    task_ids = set()
    for t in tasks:
        tid = str(t.get("id", ""))
        if not tid:
            issue("error", "card", "?", "Task has no ID")
            continue
        if tid in task_ids:
            issue("warning", "card", tid, "Duplicate task ID")
            continue
        task_ids.add(tid)

        if not t.get("title", "").strip():
            issue("error", "card", tid, "Task has no title")

        pid = str(t.get("project_id", ""))
        if pid and pid not in project_ids:
            issue("warning", "card", tid, f"Task references unknown project {pid}")

        if len(t.get("description", "")) > 32000:
            issue("warning", "card", tid, "Description exceeds 32000 chars — will be truncated")

        due = t.get("date_due", 0)
        if due and not isinstance(due, int) and not isinstance(due, str):
            issue("info", "card", tid, "Non-numeric due date — will be ignored")

    # 3. Validate comments
    for c in comments:
        cid = str(c.get("id", ""))
        task_id = str(c.get("task_id", ""))
        if not cid:
            issue("error", "comment", "?", "Comment has no ID")
        if task_id and task_id not in task_ids:
            issue("warning", "comment", cid, f"Comment references unknown task {task_id}")

    # 4. Column coverage check
    all_columns = {t.get("column_name", "") for t in tasks if t.get("column_name")}
    if len(all_columns) > 10:
        issue("warning", "column", "-", f"High column count ({len(all_columns)}) — consider consolidation")

    # Build summary
    mapped = map_full_kanboard_export(projects, tasks, comments)
    report.summary = (
        f"{mapped.total_projects} projects, {mapped.total_cards} cards, "
        f"{mapped.total_comments} comments, {mapped.total_columns} columns. "
        f"{report.errors} errors, {report.warnings} warnings."
    )

    report.is_valid = report.errors == 0
    return report


def _add_issue(report: ValidationReport):
    """Return a closure that adds an issue and updates counts."""
    def add(severity: str, entity: str, source_id: str, message: str) -> None:
        report.issues.append(ValidationIssue(
            severity=severity, entity=entity, source_id=source_id, message=message
        ))
        report.total_issues += 1
        if severity == "error":
            report.errors += 1
        elif severity == "warning":
            report.warnings += 1
        else:
            report.infos += 1
    return add
