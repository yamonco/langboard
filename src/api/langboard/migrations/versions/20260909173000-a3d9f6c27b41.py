"""allow one user identity link per provider and issuer

Revision ID: a3d9f6c27b41
Revises: 6f4a9d18c2e1
Create Date: 2026-09-09 17:30:00
"""

from collections.abc import Sequence
from alembic import op


revision: str = "a3d9f6c27b41"
down_revision: str | None = "6f4a9d18c2e1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Permit distinct issuer-scoped identities for the same provider."""

    with op.batch_alter_table("user_identity_link", schema=None) as batch_op:
        batch_op.drop_constraint("uq_user_identity_link_user_provider", type_="unique")
        batch_op.create_unique_constraint(
            "uq_user_identity_link_user_provider_issuer",
            ["user_id", "provider", "issuer"],
        )


def downgrade() -> None:
    """Restore the single provider link constraint when rows remain compatible."""

    with op.batch_alter_table("user_identity_link", schema=None) as batch_op:
        batch_op.drop_constraint("uq_user_identity_link_user_provider_issuer", type_="unique")
        batch_op.create_unique_constraint(
            "uq_user_identity_link_user_provider",
            ["user_id", "provider"],
        )
