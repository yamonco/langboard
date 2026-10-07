"""Persist INTERNAL card visibility and private disclosure audit evidence.

Deploy only with all card access and socket publication boundaries enforced.
Legacy cards remain INTERNAL; membership changes never widen visibility.
"""

import sqlalchemy as sa
from alembic import op
from langboard_shared.core.db import SnowflakeIDType


revision = "1b392df0a6ce"
down_revision = "7ca19d80e3b2"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("card") as batch:
        batch.add_column(sa.Column("visibility", sa.String(), nullable=False, server_default="INTERNAL"))
        batch.create_check_constraint("card_visibility", "visibility IN ('INTERNAL', 'SHARED')")
        batch.create_index("ix_card_project_visibility", ["project_id", "visibility"])
    op.create_table(
        "card_visibility_change",
        sa.Column("id", SnowflakeIDType(), primary_key=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("card_id", SnowflakeIDType(), sa.ForeignKey("card.id"), nullable=False),
        sa.Column("changed_by_user_id", SnowflakeIDType(), sa.ForeignKey("user.id"), nullable=True),
        sa.Column("changed_by_bot_id", SnowflakeIDType(), sa.ForeignKey("bot.id"), nullable=True),
        sa.Column("channel", sa.String(), nullable=False),
        sa.Column("previous_visibility", sa.String(), nullable=False),
        sa.Column("next_visibility", sa.String(), nullable=False),
        sa.CheckConstraint("previous_visibility IN ('INTERNAL', 'SHARED')", name="visibility_change_previous"),
        sa.CheckConstraint("next_visibility IN ('INTERNAL', 'SHARED')", name="visibility_change_next"),
        sa.CheckConstraint("previous_visibility <> next_visibility", name="visibility_change_distinct"),
        sa.CheckConstraint("(changed_by_user_id IS NULL) <> (changed_by_bot_id IS NULL)", name="visibility_change_actor"),
        sa.CheckConstraint("channel IN ('human_ui','mcp','api','bot')", name="visibility_change_channel"),
        sa.CheckConstraint("next_visibility <> 'SHARED' OR (channel = 'human_ui' AND changed_by_bot_id IS NULL)", name="visibility_change_human_share"),
    )
    op.create_index("ix_card_visibility_change_card_created", "card_visibility_change", ["card_id", "created_at", "id"])


def downgrade():
    connection = op.get_bind()
    if connection.execute(sa.text("SELECT 1 FROM card WHERE visibility = 'INTERNAL' LIMIT 1")).first():
        raise RuntimeError("Internal cards must be explicitly migrated before removing visibility protection")
    if connection.execute(sa.text("SELECT 1 FROM card_visibility_change LIMIT 1")).first():
        raise RuntimeError("Visibility audit records must be explicitly retained before removing their table")
    op.drop_table("card_visibility_change")
    with op.batch_alter_table("card") as batch:
        batch.drop_index("ix_card_project_visibility")
        batch.drop_constraint("card_visibility", type_="check")
        batch.drop_column("visibility")
