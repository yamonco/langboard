"""add sample project templates

Revision ID: 7c1f0d6a2e54
Revises: 49a7df932f2b
Create Date: 2026-08-07 19:30:00
"""

from typing import Sequence, Union
import sqlalchemy as sa
from alembic import op


revision: str = "7c1f0d6a2e54"
down_revision: Union[str, None] = "49a7df932f2b"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


SAMPLE_TEMPLATES = (
    (2, "Software-Delivery", ("Backlog", "Selected", "In Development", "Code Review", "QA", "Released")),
    (3, "Bug-Triage", ("Reported", "Triage", "Confirmed", "Fixing", "Verification", "Resolved")),
    (4, "Product-Discovery", ("Ideas", "Research", "Opportunity", "Experiment", "Decision")),
    (5, "Client-Delivery", ("Intake", "Scoping", "Proposal", "Approved", "Delivery", "Client Review", "Completed")),
    (6, "Sales", ("Leads", "Qualified", "Proposal", "Negotiation", "Closed")),
    (7, "Content", ("Ideas", "Brief", "Draft", "Editing", "Scheduled", "Published")),
    (8, "Hiring", ("Applicants", "Screening", "Interview", "Reference Check", "Offer", "Hired")),
    (9, "Incident", ("Reported", "Investigating", "Mitigating", "Monitoring", "Resolved")),
    (10, "Support", ("New", "Triaged", "Assigned", "In Progress", "Waiting for Customer", "Resolved")),
    (
        11,
        "Request-Approval",
        ("Submitted", "Clarification", "Under Review", "Changes Requested", "Approved", "Implemented"),
    ),
)

project_template = sa.table(
    "project_template",
    sa.column("id", sa.BigInteger()),
    sa.column("name", sa.String()),
    sa.column("columns", sa.JSON()),
    sa.column("internal_bots", sa.JSON()),
    sa.column("project_bot_scopes", sa.JSON()),
    sa.column("column_bot_scopes", sa.JSON()),
    sa.column("is_builtin", sa.Boolean()),
    sa.column("is_default", sa.Boolean()),
)


def _rows_to_insert(existing: Sequence[tuple[int, str]]) -> list[dict[str, object]]:
    existing_ids = {item[0] for item in existing}
    existing_names = {item[1] for item in existing}
    rows: list[dict[str, object]] = []
    for template_id, name, columns in SAMPLE_TEMPLATES:
        if name in existing_names:
            continue
        if template_id in existing_ids:
            raise RuntimeError(f"Reserved sample project template ID is already used: {template_id}")
        rows.append(
            {
                "id": template_id,
                "name": name,
                "columns": list(columns),
                "internal_bots": [],
                "project_bot_scopes": [],
                "column_bot_scopes": [],
                "is_builtin": True,
                "is_default": False,
            }
        )
    return rows


def upgrade() -> None:
    """Insert missing built-ins without replacing user templates or defaults."""

    existing = list(op.get_bind().execute(sa.select(project_template.c.id, project_template.c.name)).tuples())
    rows = _rows_to_insert(existing)
    if rows:
        op.bulk_insert(project_template, rows)


def downgrade() -> None:
    """Keep user-visible templates and default selections intact."""
