"""add edge email recipients and delivery status

Revision ID: 91f7b2c4d8e6
Revises: 3b1a0c5d7e9f
Create Date: 2026-08-20 10:00:00
"""

from typing import Sequence, Union
import sqlalchemy as sa
from alembic import op


revision: str = "91f7b2c4d8e6"
down_revision: Union[str, None] = "3b1a0c5d7e9f"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Extend a board policy without copying external addresses into templates."""

    op.add_column(
        "project_email_notification_policy",
        sa.Column("external_recipient_emails", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
    )
    op.add_column(
        "project_email_notification_policy",
        sa.Column("last_delivery_status", sa.String(length=20), nullable=True),
    )
    op.add_column(
        "project_email_notification_policy",
        sa.Column("last_delivery_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "project_email_notification_policy",
        sa.Column("last_delivery_recipient_email", sa.String(length=320), nullable=True),
    )
    op.add_column(
        "project_email_notification_policy",
        sa.Column("last_delivery_error", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    """Remove edge recipients and delivery status."""

    op.drop_column("project_email_notification_policy", "last_delivery_error")
    op.drop_column("project_email_notification_policy", "last_delivery_recipient_email")
    op.drop_column("project_email_notification_policy", "last_delivery_at")
    op.drop_column("project_email_notification_policy", "last_delivery_status")
    op.drop_column("project_email_notification_policy", "external_recipient_emails")
