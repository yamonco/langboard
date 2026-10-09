"""Add explicit global title aliases without changing existing label identities."""

import sqlalchemy as sa
from alembic import op


revision = "862af3c591d7"
down_revision = "7c98451eab03"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("global_label") as batch:
        batch.add_column(sa.Column("aliases", sa.JSON(), nullable=False, server_default=sa.text("'[]'")))
    with op.batch_alter_table("global_label") as batch:
        batch.alter_column("aliases", existing_type=sa.JSON(), server_default=None)


def downgrade():
    rows = op.get_bind().execute(sa.text("SELECT aliases FROM global_label")).scalars()
    if any(value not in ([], "[]", None) for value in rows):
        raise RuntimeError("Cannot discard registered global label aliases")
    with op.batch_alter_table("global_label") as batch:
        batch.drop_column("aliases")
