"""add typed linked resources to cards

Revision ID: 3a6f8c1d2e4b
Revises: da39f306364b
Create Date: 2026-09-10 10:30:00
"""

from typing import Sequence, Union
import sqlalchemy as sa
from alembic import op


revision: str = "3a6f8c1d2e4b"
down_revision: Union[str, None] = "da39f306364b"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Store source identity without copying source content into cards."""

    inspector = sa.inspect(op.get_bind())
    columns = {column["name"] for column in inspector.get_columns("card")}
    unique_constraints = {
        constraint["name"] for constraint in inspector.get_unique_constraints("card") if constraint.get("name")
    }
    check_constraints = {
        constraint["name"] for constraint in inspector.get_check_constraints("card") if constraint.get("name")
    }
    check_constraint = op.f("ck_card_linked_source_complete")
    with op.batch_alter_table("card", schema=None) as batch_op:
        if "source_type" not in columns:
            batch_op.add_column(sa.Column("source_type", sa.String(), nullable=True))
        if "source_uid" not in columns:
            batch_op.add_column(sa.Column("source_uid", sa.String(), nullable=True))
        if check_constraint not in check_constraints:
            batch_op.create_check_constraint(
                check_constraint,
                "(source_type IS NULL) = (source_uid IS NULL)",
            )
        if "uq_card_linked_resource" not in unique_constraints:
            batch_op.create_unique_constraint(
                "uq_card_linked_resource",
                ["project_id", "source_type", "source_uid"],
            )


def downgrade() -> None:
    """Remove linked-resource identity while preserving ordinary cards."""

    inspector = sa.inspect(op.get_bind())
    columns = {column["name"] for column in inspector.get_columns("card")}
    unique_constraints = {
        constraint["name"] for constraint in inspector.get_unique_constraints("card") if constraint.get("name")
    }
    check_constraints = {
        constraint["name"] for constraint in inspector.get_check_constraints("card") if constraint.get("name")
    }
    check_constraint = op.f("ck_card_linked_source_complete")
    with op.batch_alter_table("card", schema=None) as batch_op:
        if "uq_card_linked_resource" in unique_constraints:
            batch_op.drop_constraint("uq_card_linked_resource", type_="unique")
        if check_constraint in check_constraints:
            batch_op.drop_constraint(check_constraint, type_="check")
        if "source_uid" in columns:
            batch_op.drop_column("source_uid")
        if "source_type" in columns:
            batch_op.drop_column("source_type")
