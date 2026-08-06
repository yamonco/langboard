"""add project templates

Revision ID: 49a7df932f2b
Revises: 908b2f9f42d1
Create Date: 2026-08-06 22:00:00
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "49a7df932f2b"
down_revision: Union[str, None] = "908b2f9f42d1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create template storage; the domain service materializes built-ins."""

    op.create_table(
        "project_template",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("columns", sa.JSON(), nullable=False),
        sa.Column("internal_bots", sa.JSON(), nullable=False),
        sa.Column("project_bot_scopes", sa.JSON(), nullable=False),
        sa.Column("column_bot_scopes", sa.JSON(), nullable=False),
        sa.Column("is_builtin", sa.Boolean(), nullable=False),
        sa.Column("is_default", sa.Boolean(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_project_template")),
        sa.UniqueConstraint("name", name=op.f("uq_project_template_name")),
    )
    op.create_index(op.f("ix_project_template_is_default"), "project_template", ["is_default"], unique=False)
    op.create_index(op.f("ix_project_template_name"), "project_template", ["name"], unique=False)


def downgrade() -> None:
    """Remove project template storage."""

    op.drop_index(op.f("ix_project_template_name"), table_name="project_template")
    op.drop_index(op.f("ix_project_template_is_default"), table_name="project_template")
    op.drop_table("project_template")
