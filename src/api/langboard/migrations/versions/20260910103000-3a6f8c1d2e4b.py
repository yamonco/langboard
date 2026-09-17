"""add typed linked resources to cards

Revision ID: 3a6f8c1d2e4b
Revises: 82cd7e14a3f9
Create Date: 2026-09-10 10:30:00
"""

from typing import Sequence, Union
import sqlalchemy as sa
from alembic import op


revision: str = "3a6f8c1d2e4b"
down_revision: Union[str, None] = "82cd7e14a3f9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Store source identity without copying source content into cards."""

    inspector = sa.inspect(op.get_bind())
    card_columns = {column["name"] for column in inspector.get_columns("card")}
    card_unique_names = {
        constraint["name"] for constraint in inspector.get_unique_constraints("card") if constraint.get("name")
    }
    card_check_names = {
        constraint["name"] for constraint in inspector.get_check_constraints("card") if constraint.get("name")
    }

    with op.batch_alter_table("card", schema=None) as batch_op:
        if "source_type" not in card_columns:
            batch_op.add_column(sa.Column("source_type", sa.String(), nullable=True))
        if "source_uid" not in card_columns:
            batch_op.add_column(sa.Column("source_uid", sa.String(), nullable=True))
    with op.batch_alter_table("card", schema=None) as batch_op:
        check_name = op.f("ck_card_linked_source_complete")
        if check_name not in card_check_names:
            batch_op.create_check_constraint(
                check_name,
                "(source_type IS NULL) = (source_uid IS NULL)",
            )
        unique_name = "uq_card_linked_resource"
        if unique_name not in card_unique_names:
            batch_op.create_unique_constraint(
                unique_name,
                ["project_id", "source_type", "source_uid"],
            )


def downgrade() -> None:
    """Remove linked-resource identity while preserving ordinary cards."""

    inspector = sa.inspect(op.get_bind())
    card_columns = {column["name"] for column in inspector.get_columns("card")}
    card_unique_names = {
        constraint["name"] for constraint in inspector.get_unique_constraints("card") if constraint.get("name")
    }
    card_check_names = {
        constraint["name"] for constraint in inspector.get_check_constraints("card") if constraint.get("name")
    }

    with op.batch_alter_table("card", schema=None) as batch_op:
        unique_name = "uq_card_linked_resource"
        if unique_name in card_unique_names:
            batch_op.drop_constraint(unique_name, type_="unique")
        check_name = op.f("ck_card_linked_source_complete")
        if check_name in card_check_names:
            batch_op.drop_constraint(check_name, type_="check")
        if "source_uid" in card_columns:
            batch_op.drop_column("source_uid")
        if "source_type" in card_columns:
            batch_op.drop_column("source_type")
