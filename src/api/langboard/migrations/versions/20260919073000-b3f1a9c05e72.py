"""add organization tenant entity

Revision ID: b3f1a9c05e72
Revises: da39f306364b
Create Date: 2026-09-19 07:30:00.000000

"""

from typing import Sequence, Union
import sqlalchemy as sa
from alembic import op
from langboard_shared.core.db.ColumnTypes import SnowflakeIDType


# revision identifiers, used by Alembic.
revision: str = "b3f1a9c05e72"
down_revision: Union[str, None] = "da39f306364b"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    if "organization" in set(sa.inspect(op.get_bind()).get_table_names()):
        return
    op.create_table(
        "organization",
        sa.Column("id", SnowflakeIDType, autoincrement=False, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("slug", sa.String(), nullable=False),
        sa.Column("owner_user_id", SnowflakeIDType, nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("suspended_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["owner_user_id"], ["user.id"], name=op.f("fk_organization_owner_user_id_user"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_organization")),
        sa.UniqueConstraint("slug", name=op.f("uq_organization_slug")),
    )
    op.create_index(op.f("ix_organization_name"), "organization", ["name"], unique=False)
    op.create_index(op.f("ix_organization_slug"), "organization", ["slug"], unique=True)
    op.create_index(op.f("ix_organization_owner_user_id"), "organization", ["owner_user_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_organization_owner_user_id"), table_name="organization")
    op.drop_index(op.f("ix_organization_slug"), table_name="organization")
    op.drop_index(op.f("ix_organization_name"), table_name="organization")
    op.drop_table("organization")
