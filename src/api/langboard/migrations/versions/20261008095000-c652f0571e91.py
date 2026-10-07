"""Fence resource refreshes against lifecycle invalidation."""

import sqlalchemy as sa
from alembic import op


revision = "c652f0571e91"
down_revision = "b541ef460d80"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "app_resource_binding", sa.Column("access_revision", sa.Integer(), nullable=False, server_default="0")
    )
    op.add_column(
        "git_hub_lifecycle_receipt", sa.Column("invalidated", sa.Boolean(), nullable=False, server_default=sa.false())
    )


def downgrade():
    if op.get_bind().execute(sa.text("SELECT 1 FROM app_resource_binding WHERE access_revision != 0 LIMIT 1")).first():
        raise RuntimeError("Cannot discard resource invalidation revisions")
    if (
        op.get_bind()
        .execute(sa.text("SELECT 1 FROM git_hub_lifecycle_receipt WHERE invalidated = true LIMIT 1"))
        .first()
    ):
        raise RuntimeError("Cannot discard applied lifecycle receipts")
    with op.batch_alter_table("git_hub_lifecycle_receipt") as batch:
        batch.drop_column("invalidated")
    with op.batch_alter_table("app_resource_binding") as batch:
        batch.drop_column("access_revision")
