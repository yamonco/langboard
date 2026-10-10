"""Persist creation-only PRIVATE ownership without activating access surfaces.

Deploy only with complete owner-scoped access and publication boundaries.
"""

import sqlalchemy as sa
from alembic import op
from langboard_shared.core.db import SnowflakeIDType


revision = "3d5a71e8c942"
down_revision = "1b392df0a6ce"
branch_labels = None
depends_on = None

OWNER_CHECK = (
    "(visibility = 'PRIVATE' AND owner_user_id IS NOT NULL AND owner_user_id > 0 "
    "AND created_by_user_id IS NOT NULL AND owner_user_id = created_by_user_id "
    "AND created_by_bot_id IS NULL) OR (visibility <> 'PRIVATE' AND owner_user_id IS NULL)"
)


def _dialect():
    dialect = op.get_bind().dialect.name
    if dialect not in {"sqlite", "postgresql"}:
        raise RuntimeError("PRIVATE ownership migration requires SQLite or PostgreSQL")
    return dialect


def upgrade():
    dialect = _dialect()
    with op.batch_alter_table("card") as batch:
        batch.add_column(sa.Column("owner_user_id", SnowflakeIDType(), nullable=True))
        batch.create_foreign_key("fk_card_private_owner", "user", ["owner_user_id"], ["id"])
        batch.drop_constraint("card_visibility", type_="check")
        batch.create_check_constraint("card_visibility", "visibility IN ('INTERNAL', 'SHARED', 'PRIVATE')")
        batch.create_check_constraint("card_private_owner", OWNER_CHECK)
    if dialect == "sqlite":
        op.execute("""
            CREATE TRIGGER card_private_immutable BEFORE UPDATE ON card
            WHEN (OLD.visibility = 'PRIVATE' OR NEW.visibility = 'PRIVATE') AND
                 (OLD.visibility IS NOT NEW.visibility OR OLD.owner_user_id IS NOT NEW.owner_user_id)
            BEGIN SELECT RAISE(ABORT, 'PRIVATE visibility and owner are immutable'); END
        """)
    else:
        op.execute("""
            CREATE FUNCTION guard_card_private_immutable() RETURNS trigger LANGUAGE plpgsql AS $$
            BEGIN
                IF (OLD.visibility = 'PRIVATE' OR NEW.visibility = 'PRIVATE') AND
                   (OLD.visibility IS DISTINCT FROM NEW.visibility OR
                    OLD.owner_user_id IS DISTINCT FROM NEW.owner_user_id) THEN
                    RAISE EXCEPTION 'PRIVATE visibility and owner are immutable' USING ERRCODE = '23514';
                END IF;
                RETURN NEW;
            END;
            $$
        """)
        op.execute("""
            CREATE TRIGGER card_private_immutable BEFORE UPDATE ON card
            FOR EACH ROW EXECUTE FUNCTION guard_card_private_immutable()
        """)


def downgrade():
    dialect = _dialect()
    if op.get_bind().execute(sa.text("SELECT 1 FROM card WHERE visibility = 'PRIVATE' LIMIT 1")).first():
        raise RuntimeError("PRIVATE cards must be explicitly retained before removing ownership protection")
    if dialect == "sqlite":
        op.execute("DROP TRIGGER card_private_immutable")
    else:
        op.execute("DROP TRIGGER card_private_immutable ON card")
        op.execute("DROP FUNCTION guard_card_private_immutable()")
    with op.batch_alter_table("card") as batch:
        batch.drop_constraint("card_private_owner", type_="check")
        batch.drop_constraint("card_visibility", type_="check")
        batch.create_check_constraint("card_visibility", "visibility IN ('INTERNAL', 'SHARED')")
        batch.drop_constraint("fk_card_private_owner", type_="foreignkey")
        batch.drop_column("owner_user_id")
