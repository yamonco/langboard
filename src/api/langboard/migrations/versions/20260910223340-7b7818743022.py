"""scope external identity subjects by issuer

Revision ID: 7b7818743022
Revises: da39f306364b
Create Date: 2026-09-10 22:33:40.261318

"""

from collections.abc import Sequence
import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision: str = "7b7818743022"
down_revision: str | None = "da39f306364b"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Backfill legacy links before making issuer part of the durable key."""

    op.execute(sa.text("UPDATE user_identity_link SET issuer = '' WHERE issuer IS NULL"))
    op.alter_column("user_identity_link", "issuer", existing_type=sa.VARCHAR(), nullable=False)
    op.drop_constraint(
        op.f("uq_user_identity_link_provider_external_id"),
        "user_identity_link",
        type_="unique",
    )
    op.create_unique_constraint(
        "uq_user_identity_link_provider_issuer_external_id",
        "user_identity_link",
        ["provider", "external_id", "issuer"],
    )


def downgrade() -> None:
    """Restore the legacy provider-subject key when values remain compatible."""

    op.drop_constraint(
        "uq_user_identity_link_provider_issuer_external_id",
        "user_identity_link",
        type_="unique",
    )
    op.create_unique_constraint(
        op.f("uq_user_identity_link_provider_external_id"),
        "user_identity_link",
        ["provider", "external_id"],
        postgresql_nulls_not_distinct=False,
    )
    op.alter_column("user_identity_link", "issuer", existing_type=sa.VARCHAR(), nullable=True)
    op.execute(sa.text("UPDATE user_identity_link SET issuer = NULL WHERE issuer = ''"))
