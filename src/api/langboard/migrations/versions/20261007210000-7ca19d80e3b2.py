"""Keep structural Docling artifacts out of attachment response projections."""

import sqlalchemy as sa
from alembic import op
from langboard_shared.core.db import SnowflakeIDType


revision = "7ca19d80e3b2"
down_revision = "6b9e17ac042d"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "card_document_artifact",
        sa.Column("id", SnowflakeIDType(), primary_key=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("attachment_id", SnowflakeIDType(), sa.ForeignKey("card_attachment.id"), nullable=False, unique=True),
        sa.Column("document_json", sa.Text(), nullable=False),
    )


def downgrade():
    op.drop_table("card_document_artifact")
