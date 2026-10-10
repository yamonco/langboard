"""Persist app policy scopes and preserve existing personal connection owners."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.schema import conv


revision = "d73ef84a91c2"
down_revision = "c62943df05b8"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "app_governance_policy",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("scope_key", sa.String(), nullable=False),
        sa.Column("organization_id", sa.BigInteger(), sa.ForeignKey("organization.id"), nullable=True, unique=True),
        sa.Column("mode", sa.String(), nullable=True),
        sa.Column("generation", sa.Integer(), nullable=False),
        sa.CheckConstraint(
            "(mode IS NOT NULL AND mode IN ('disabled','approved_only','personal_allowed')) OR "
            "(mode IS NULL AND organization_id IS NOT NULL)",
            name=conv("ck_app_governance_policy_mode"),
        ),
        sa.CheckConstraint(
            "(scope_key = 'global' AND organization_id IS NULL) OR "
            "(organization_id IS NOT NULL AND scope_key = 'organization:' || CAST(organization_id AS VARCHAR))",
            name=conv("ck_app_governance_policy_scope"),
        ),
    )
    op.create_index("ix_app_governance_policy_scope_key", "app_governance_policy", ["scope_key"], unique=True)
    with op.batch_alter_table("app_connection") as batch:
        batch.add_column(sa.Column("ownership", sa.String(), nullable=False, server_default="personal"))
        batch.add_column(sa.Column("organization_id", sa.BigInteger(), nullable=True))
        batch.create_foreign_key(
            "fk_app_connection_organization_id_organization", "organization", ["organization_id"], ["id"]
        )
        batch.create_index("ix_app_connection_organization_id", ["organization_id"])
        batch.create_check_constraint(
            conv("ck_app_connection_ownership"),
            "(ownership = 'personal' AND organization_id IS NULL) OR "
            "(ownership = 'organization' AND organization_id IS NOT NULL)",
        )


def downgrade():
    connection = op.get_bind()
    if connection.execute(sa.text("SELECT 1 FROM app_governance_policy LIMIT 1")).first():
        raise RuntimeError("Cannot discard app governance policy")
    if connection.execute(sa.text("SELECT 1 FROM app_connection WHERE ownership = 'organization' LIMIT 1")).first():
        raise RuntimeError("Cannot discard organization connection ownership")
    with op.batch_alter_table("app_connection") as batch:
        batch.drop_constraint(conv("ck_app_connection_ownership"), type_="check")
        batch.drop_index("ix_app_connection_organization_id")
        batch.drop_constraint("fk_app_connection_organization_id_organization", type_="foreignkey")
        batch.drop_column("organization_id")
        batch.drop_column("ownership")
    op.drop_table("app_governance_policy")
