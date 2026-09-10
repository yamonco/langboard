"""add provider-neutral external import lineage

Revision ID: 54e9c7a1d230
Revises: da39f306364b
Create Date: 2026-09-10 12:30:00
"""

from collections.abc import Sequence
import sqlalchemy as sa
from alembic import op


revision: str = "54e9c7a1d230"
down_revision: str | None = "da39f306364b"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "external_import_record",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("project_id", sa.BigInteger(), nullable=False),
        sa.Column("source_namespace", sa.String(), nullable=False),
        sa.Column("source_container_id", sa.String(), nullable=False),
        sa.Column("record_type", sa.String(), nullable=False),
        sa.Column("source_record_id", sa.String(), nullable=False),
        sa.Column("target_type", sa.String(), nullable=False),
        sa.Column("target_uid", sa.String(), nullable=False),
        sa.Column("source_fingerprint", sa.String(), nullable=False),
        sa.Column("batch_id", sa.String(), nullable=False),
        sa.Column("provenance", sa.Text(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("effects_dispatched_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("effects_attempts", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("effects_error", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["project.id"],
            name=op.f("fk_external_import_record_project_id_project"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_external_import_record")),
        sa.UniqueConstraint(
            "project_id",
            "source_namespace",
            "source_container_id",
            "record_type",
            "source_record_id",
            name="uq_external_import_record_source_record",
        ),
        if_not_exists=True,
    )
    op.create_index(
        op.f("ix_external_import_record_project_id"),
        "external_import_record",
        ["project_id"],
        if_not_exists=True,
    )
    op.create_index(
        op.f("ix_external_import_record_source_namespace"),
        "external_import_record",
        ["source_namespace"],
        if_not_exists=True,
    )
    op.create_index(
        op.f("ix_external_import_record_record_type"),
        "external_import_record",
        ["record_type"],
        if_not_exists=True,
    )
    op.create_index(
        op.f("ix_external_import_record_batch_id"),
        "external_import_record",
        ["batch_id"],
        if_not_exists=True,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_external_import_record_batch_id"), table_name="external_import_record", if_exists=True)
    op.drop_index(op.f("ix_external_import_record_record_type"), table_name="external_import_record", if_exists=True)
    op.drop_index(op.f("ix_external_import_record_source_namespace"), table_name="external_import_record", if_exists=True)
    op.drop_index(op.f("ix_external_import_record_project_id"), table_name="external_import_record", if_exists=True)
    op.drop_table("external_import_record", if_exists=True)
