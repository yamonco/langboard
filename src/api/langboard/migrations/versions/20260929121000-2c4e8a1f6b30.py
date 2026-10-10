"""Add explicit relationship semantics without reclassifying legacy edges.

Revision ID: 2c4e8a1f6b30
Revises: 7ad15b1d0b70
"""

from typing import Sequence, Union
import sqlalchemy as sa
from alembic import op
from langboard_shared.core.types import SnowflakeID


revision: str = "2c4e8a1f6b30"
down_revision: Union[str, None] = "7ad15b1d0b70"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


DEFAULT_RELATIONSHIPS = (
    ("contains", "포함", "소속", "계획·기능 구성 관계", False),
    ("blocks", "선행작업", "후속작업", "실제 실행 선행조건", True),
    ("references", "참고", "관련", "문맥·설계·근거 연결", False),
)


def upgrade() -> None:
    with op.batch_alter_table("global_card_relationship_type") as batch_op:
        batch_op.add_column(sa.Column("machine_semantic", sa.String(), nullable=True))
        batch_op.add_column(sa.Column("is_system_default", sa.Boolean(), nullable=False, server_default=sa.false()))
        batch_op.add_column(sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()))
        batch_op.add_column(sa.Column("affects_readiness", sa.Boolean(), nullable=False, server_default=sa.false()))
        batch_op.create_check_constraint(
            "ck_global_relationship_machine_semantic",
            "machine_semantic IS NULL OR machine_semantic IN ('contains', 'blocks', 'references')",
        )
    op.create_index(
        "uq_global_relationship_system_semantic",
        "global_card_relationship_type",
        ["machine_semantic"],
        unique=True,
        postgresql_where=sa.text("is_system_default"),
    )

    # The audited one-type legacy installation must not create more ambiguous edges.
    # Keep its UID and every old edge, but hide the unclassified type from new selections.
    bind = op.get_bind()
    existing = bind.execute(sa.text("SELECT id, parent_name, child_name FROM global_card_relationship_type")).all()
    if len(existing) == 1 and existing[0].parent_name == "선행작업" and existing[0].child_name == "후속작업":
        bind.execute(
            sa.text("UPDATE global_card_relationship_type SET is_active = false WHERE id = :id"),
            {"id": existing[0].id},
        )
    for semantic, parent, child, description, blocks in DEFAULT_RELATIONSHIPS:
        bind.execute(
            sa.text(
                """INSERT INTO global_card_relationship_type
                   (id, created_at, updated_at, parent_name, child_name, description,
                    machine_semantic, is_system_default, is_active, affects_readiness)
                   VALUES (:id, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, :parent, :child, :description,
                           :semantic, true, true, :blocks)"""
            ),
            {
                "id": int(SnowflakeID()),
                "parent": parent,
                "child": child,
                "description": description,
                "semantic": semantic,
                "blocks": blocks,
            },
        )


def downgrade() -> None:
    bind = op.get_bind()
    in_use = bind.execute(
        sa.text(
            """SELECT COUNT(*) FROM card_relationship r
               JOIN global_card_relationship_type t ON t.id = r.relationship_type_id
               WHERE t.is_system_default"""
        )
    ).scalar_one()
    if in_use:
        raise RuntimeError("System relationship types have edges; downgrade requires explicit migration")
    bind.execute(sa.text("DELETE FROM global_card_relationship_type WHERE is_system_default"))
    op.drop_index("uq_global_relationship_system_semantic", table_name="global_card_relationship_type")
    with op.batch_alter_table("global_card_relationship_type") as batch_op:
        batch_op.drop_constraint("ck_global_relationship_machine_semantic", type_="check")
        for name in ("affects_readiness", "is_active", "is_system_default", "machine_semantic"):
            batch_op.drop_column(name)
