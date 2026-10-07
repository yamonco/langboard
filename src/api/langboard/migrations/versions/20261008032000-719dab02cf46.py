"""Persist independent App connections and board resource bindings."""

import sqlalchemy as sa
from alembic import op


revision = "719dab02cf46"
down_revision = "48f716ecb2d0"
branch_labels = None
depends_on = None


def base_columns():
    return [
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    ]


def upgrade():
    op.create_table(
        "app_connection",
        *base_columns(),
        sa.Column("app_key", sa.String(), nullable=False),
        sa.Column("owner_id", sa.BigInteger(), sa.ForeignKey("user.id"), nullable=False),
        sa.Column("instance_url", sa.String(), nullable=False),
        sa.Column("external_account_id", sa.String(), nullable=False),
        sa.Column("credential_reference", sa.String(), nullable=True),
        sa.Column("state", sa.String(), nullable=False),
        sa.CheckConstraint("state IN ('pending','connected','revoked','disconnected')", name="ck_app_connection_state"),
    )
    op.create_table(
        "board_app_binding",
        *base_columns(),
        sa.Column("project_id", sa.BigInteger(), sa.ForeignKey("project.id"), nullable=False),
        sa.Column("app_key", sa.String(), nullable=False),
        sa.Column("state", sa.String(), nullable=False),
        sa.Column("workflow_mapping", sa.JSON(), nullable=False),
        sa.Column("granted_capabilities", sa.JSON(), nullable=False),
        sa.Column("stage_transitions_enabled", sa.Boolean(), nullable=False),
        sa.UniqueConstraint("project_id", "app_key", name="uq_board_app_binding_project_app"),
        sa.CheckConstraint(
            "state IN ('disabled','enabled','needs_attention','disconnected')", name="ck_board_app_binding_state"
        ),
    )
    op.create_table(
        "app_resource_binding",
        *base_columns(),
        sa.Column("board_binding_id", sa.BigInteger(), sa.ForeignKey("board_app_binding.id"), nullable=False),
        sa.Column("connection_id", sa.BigInteger(), sa.ForeignKey("app_connection.id"), nullable=False),
        sa.Column("resource_type", sa.String(), nullable=False),
        sa.Column("external_resource_id", sa.String(), nullable=False),
        sa.Column("resource_path", sa.JSON(), nullable=False),
        sa.Column("is_selected", sa.Boolean(), nullable=False),
        sa.Column("access_state", sa.String(), nullable=False),
        sa.Column("health", sa.String(), nullable=False),
        sa.UniqueConstraint(
            "board_binding_id",
            "connection_id",
            "resource_type",
            "external_resource_id",
            name="uq_app_resource_binding_identity",
        ),
        sa.CheckConstraint(
            "access_state IN ('unknown','granted','denied','revoked')", name="ck_app_resource_access_state"
        ),
        sa.CheckConstraint("health IN ('unknown','healthy','degraded','unavailable')", name="ck_app_resource_health"),
    )
    for table, columns in {
        "app_connection": ("app_key", "owner_id"),
        "board_app_binding": ("project_id",),
        "app_resource_binding": ("board_binding_id", "connection_id"),
    }.items():
        for column in columns:
            op.create_index(f"ix_{table}_{column}", table, [column])


def downgrade():
    # Unlink through the host first. Do not silently erase credentials/provenance.
    for table in ("app_resource_binding", "board_app_binding", "app_connection"):
        if op.get_bind().execute(sa.text(f"SELECT 1 FROM {table} LIMIT 1")).first():
            raise RuntimeError("App bindings must be explicitly removed before downgrade")
    for table in ("app_resource_binding", "board_app_binding", "app_connection"):
        op.drop_table(table)
