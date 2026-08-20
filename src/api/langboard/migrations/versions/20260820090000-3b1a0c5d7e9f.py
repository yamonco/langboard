"""add per-project email notification policy

Revision ID: 3b1a0c5d7e9f
Revises: b8e42f0c9a31
Create Date: 2026-08-20 09:00:00
"""

from typing import Sequence, Union
import sqlalchemy as sa
from alembic import op


revision: str = "3b1a0c5d7e9f"
down_revision: Union[str, None] = "b8e42f0c9a31"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None
SI_EMAIL_NOTIFICATION_POLICY = {
    "is_enabled": True,
    "notify_all_members": True,
    "categories": ["cards"],
    "card_move_target_columns": ["Review"],
}


def upgrade() -> None:
    """Create board-owned policy and normalized member recipients."""

    op.create_table(
        "project_email_notification_policy",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("project_id", sa.BigInteger(), nullable=False),
        sa.Column("is_enabled", sa.Boolean(), nullable=False),
        sa.Column("notify_all_members", sa.Boolean(), nullable=False),
        sa.Column("categories", sa.Text(), nullable=False),
        sa.Column("card_move_target_columns", sa.JSON(), nullable=False),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["project.id"],
            name=op.f("fk_project_email_notification_policy_project_id_project"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_project_email_notification_policy")),
        sa.UniqueConstraint("project_id", name=op.f("uq_project_email_notification_policy_project_id")),
    )
    op.create_index(
        op.f("ix_project_email_notification_policy_project_id"),
        "project_email_notification_policy",
        ["project_id"],
        unique=True,
    )
    op.create_table(
        "project_email_notification_recipient",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("policy_id", sa.BigInteger(), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.ForeignKeyConstraint(
            ["policy_id"],
            ["project_email_notification_policy.id"],
            name=op.f("fk_project_email_notification_recipient_policy_id_project_email_notification_policy"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["user.id"],
            name=op.f("fk_project_email_notification_recipient_user_id_user"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_project_email_notification_recipient")),
        sa.UniqueConstraint("policy_id", "user_id", name="uq_project_email_notification_recipient_policy_user"),
    )
    op.create_index(
        op.f("ix_project_email_notification_recipient_policy_id"),
        "project_email_notification_recipient",
        ["policy_id"],
        unique=False,
    )
    op.add_column(
        "project_template",
        sa.Column("email_notification_policy", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
    )
    project_template = sa.table(
        "project_template",
        sa.column("name", sa.String()),
        sa.column("email_notification_policy", sa.JSON()),
    )
    op.get_bind().execute(
        project_template.update()
        .where(project_template.c.name == "SI")
        .values(email_notification_policy=SI_EMAIL_NOTIFICATION_POLICY)
    )
    op.create_index(
        op.f("ix_project_email_notification_recipient_user_id"),
        "project_email_notification_recipient",
        ["user_id"],
        unique=False,
    )


def downgrade() -> None:
    """Remove board email notification policy storage."""

    op.drop_column("project_template", "email_notification_policy")
    op.drop_index(
        op.f("ix_project_email_notification_recipient_user_id"),
        table_name="project_email_notification_recipient",
    )
    op.drop_index(
        op.f("ix_project_email_notification_recipient_policy_id"),
        table_name="project_email_notification_recipient",
    )
    op.drop_table("project_email_notification_recipient")
    op.drop_index(
        op.f("ix_project_email_notification_policy_project_id"),
        table_name="project_email_notification_policy",
    )
    op.drop_table("project_email_notification_policy")
