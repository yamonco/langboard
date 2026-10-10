"""Preserve template column translations on created boards."""

import sqlalchemy as sa
from alembic import op


revision = "2f8c4d0e9a61"
down_revision = "8c2ab63d914e"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("project_column") as batch:
        batch.add_column(sa.Column("translations", sa.JSON(), nullable=False, server_default="{}"))


def downgrade():
    if (
        op.get_bind()
        .execute(sa.text("SELECT 1 FROM project_column WHERE CAST(translations AS TEXT) <> '{}' LIMIT 1"))
        .first()
    ):
        raise RuntimeError("Preserve column translations before downgrade")
    with op.batch_alter_table("project_column") as batch:
        batch.drop_column("translations")
