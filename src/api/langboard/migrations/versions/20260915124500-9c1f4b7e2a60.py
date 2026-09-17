"""Preserve nullable original card authors without inferring legacy identities.

Revision ID: 9c1f4b7e2a60
Revises: 404967cb79df
"""

import sqlalchemy as sa
from alembic import op
from langboard_shared.core.db.ColumnTypes import SnowflakeIDType


revision = "9c1f4b7e2a60"
down_revision = "404967cb79df"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        for name in ("created_by_user_id", "created_by_bot_id"):
            op.execute(sa.text(f"ALTER TABLE card ADD COLUMN IF NOT EXISTS {name} BIGINT"))
            op.execute(sa.text(f"CREATE INDEX IF NOT EXISTS ix_card_{name} ON card ({name})"))
        return
    existing = {column["name"] for column in sa.inspect(op.get_bind()).get_columns("card")}
    indexes = {index["name"] for index in sa.inspect(op.get_bind()).get_indexes("card")}
    with op.batch_alter_table("card") as batch:
        for name in ("created_by_user_id", "created_by_bot_id"):
            if name not in existing:
                batch.add_column(sa.Column(name, SnowflakeIDType(), nullable=True))
            if f"ix_card_{name}" not in indexes:
                batch.create_index(f"ix_card_{name}", [name])


def downgrade() -> None:
    # Additive compatibility: old application versions tolerate these nullable
    # columns. Dropping them would erase immutable authors, including fields
    # already present in databases historically synchronized outside Alembic.
    pass
