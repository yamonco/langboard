"""scope external identity subjects by issuer

Revision ID: 6f4a9d18c2e1
Revises: 91f7b2c4d8e6
Create Date: 2026-09-03 23:50:00
"""

from collections.abc import Sequence
import sqlalchemy as sa
from alembic import op


revision: str = "6f4a9d18c2e1"
down_revision: str | None = "91f7b2c4d8e6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Make issuer part of the durable external identity key."""

    op.execute(sa.text("UPDATE user_identity_link SET issuer = '' WHERE issuer IS NULL"))
    with op.batch_alter_table("user_identity_link", schema=None) as batch_op:
        batch_op.alter_column("issuer", existing_type=sa.String(), nullable=False, server_default="")
        batch_op.drop_constraint("uq_user_identity_link_provider_external_id", type_="unique")
        batch_op.create_unique_constraint(
            "uq_user_identity_link_provider_issuer_external_id",
            ["provider", "issuer", "external_id"],
        )
        batch_op.alter_column("issuer", existing_type=sa.String(), server_default=None)


def downgrade() -> None:
    """Restore the legacy provider-subject key when values remain compatible."""

    with op.batch_alter_table("user_identity_link", schema=None) as batch_op:
        batch_op.drop_constraint("uq_user_identity_link_provider_issuer_external_id", type_="unique")
        batch_op.create_unique_constraint(
            "uq_user_identity_link_provider_external_id",
            ["provider", "external_id"],
        )
        batch_op.alter_column("issuer", existing_type=sa.String(), nullable=True)
    op.execute(sa.text("UPDATE user_identity_link SET issuer = NULL WHERE issuer = ''"))
