"""Bind column workflow keys to the global registry without changing existing values."""

import sqlalchemy as sa
from alembic import op


revision = "7be934f2a6c1"
down_revision = "4afb6de824d3"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("project_column") as batch:
        batch.drop_constraint("ck_project_column_workflow_stage", type_="check")
        batch.create_foreign_key(
            "fk_project_column_workflow_stage",
            "workflow_stage_definition",
            ["workflow_stage"],
            ["key"],
            ondelete="RESTRICT",
        )


def downgrade():
    connection = op.get_bind()
    if connection.execute(
        sa.text(
            "SELECT 1 FROM project_column WHERE workflow_stage NOT IN ('backlog','ready','active','review','closed','reference') LIMIT 1"
        )
    ).first():
        raise RuntimeError("Custom workflow bindings must be explicitly migrated before downgrade")
    with op.batch_alter_table("project_column") as batch:
        batch.drop_constraint("fk_project_column_workflow_stage", type_="foreignkey")
        batch.create_check_constraint(
            "ck_project_column_workflow_stage",
            "workflow_stage IS NULL OR workflow_stage IN ('backlog','ready','active','review','closed','reference')",
        )
