"""Add secret audit correlation and bounded reason codes without backfilling fiction."""

import sqlalchemy as sa
from alembic import op


revision = "e87412793ab3"
down_revision = "d76301682fa2"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("secret_reference_audit", sa.Column("request_id", sa.String(length=64), nullable=True))
    op.add_column("secret_reference_audit", sa.Column("reason_code", sa.String(length=32), nullable=True))


def downgrade():
    if (
        op.get_bind()
        .execute(
            sa.text(
                "SELECT 1 FROM secret_reference_audit WHERE request_id IS NOT NULL OR reason_code IS NOT NULL LIMIT 1"
            )
        )
        .first()
    ):
        raise RuntimeError("Cannot discard secret audit correlation evidence")
    with op.batch_alter_table("secret_reference_audit") as batch:
        batch.drop_column("reason_code")
        batch.drop_column("request_id")
