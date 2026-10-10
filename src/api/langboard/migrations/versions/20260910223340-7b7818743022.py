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


def _unique_constraint_names() -> set[str]:
    """Read the deployed constraint state so interrupted or pre-applied upgrades are safe."""

    return {
        constraint["name"]
        for constraint in sa.inspect(op.get_bind()).get_unique_constraints("user_identity_link")
        if constraint.get("name")
    }


def upgrade() -> None:
    """Backfill legacy links before making issuer part of the durable key."""

    op.execute(sa.text("UPDATE user_identity_link SET issuer = '' WHERE issuer IS NULL"))
    op.alter_column("user_identity_link", "issuer", existing_type=sa.VARCHAR(), nullable=False)
    constraints = _unique_constraint_names()
    legacy_constraint = op.f("uq_user_identity_link_provider_external_id")
    if legacy_constraint in constraints:
        op.drop_constraint(legacy_constraint, "user_identity_link", type_="unique")
    if "uq_user_identity_link_provider_issuer_external_id" not in constraints:
        op.create_unique_constraint(
            "uq_user_identity_link_provider_issuer_external_id",
            "user_identity_link",
            ["provider", "external_id", "issuer"],
        )


def downgrade() -> None:
    """Restore the legacy provider-subject key when values remain compatible."""

    duplicate = (
        op.get_bind()
        .execute(sa.text("SELECT 1 FROM user_identity_link GROUP BY provider, external_id HAVING COUNT(*) > 1 LIMIT 1"))
        .first()
    )
    if duplicate:
        raise RuntimeError(
            "Cannot downgrade user_identity_link: duplicate (provider, external_id) rows exist across issuers"
        )

    constraints = _unique_constraint_names()
    issuer_constraint = "uq_user_identity_link_provider_issuer_external_id"
    legacy_constraint = op.f("uq_user_identity_link_provider_external_id")
    if issuer_constraint in constraints:
        op.drop_constraint(issuer_constraint, "user_identity_link", type_="unique")
    if legacy_constraint not in constraints:
        op.create_unique_constraint(
            legacy_constraint,
            "user_identity_link",
            ["provider", "external_id"],
            postgresql_nulls_not_distinct=False,
        )
    op.alter_column("user_identity_link", "issuer", existing_type=sa.VARCHAR(), nullable=True)
    op.execute(sa.text("UPDATE user_identity_link SET issuer = NULL WHERE issuer = ''"))
