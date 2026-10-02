"""Persist template descriptions and explicitly selected global labels."""

import sqlalchemy as sa
from alembic import op


revision = "8c2ab63d914e"
down_revision = "7be934f2a6c1"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("project_template") as batch:
        batch.add_column(sa.Column("description", sa.Text(), nullable=False, server_default=""))
        batch.add_column(sa.Column("global_label_uids", sa.JSON(), nullable=False, server_default="[]"))


def downgrade():
    if (
        op.get_bind()
        .execute(
            sa.text(
                "SELECT 1 FROM project_template WHERE description <> '' OR CAST(global_label_uids AS TEXT) <> '[]' LIMIT 1"
            )
        )
        .first()
    ):
        raise RuntimeError("Preserve template metadata before downgrade")
    with op.batch_alter_table("project_template") as batch:
        batch.drop_column("global_label_uids")
        batch.drop_column("description")
