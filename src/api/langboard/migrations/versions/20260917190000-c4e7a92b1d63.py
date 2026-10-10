"""add checklist is_system marker

Revision ID: c4e7a92b1d63
Revises: da39f306364b
Create Date: 2026-09-17 19:00:00.000000

"""

from typing import Sequence, Union
import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision: str = 'c4e7a92b1d63'
down_revision: Union[str, None] = 'canary_integration_20260917'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()
    column_exists = conn.execute(
        sa.text("SELECT 1 FROM information_schema.columns WHERE table_name = 'checklist' AND column_name = 'is_system'")
    ).scalar()
    if not column_exists:
        op.add_column('checklist', sa.Column('is_system', sa.Boolean(), nullable=False, server_default=sa.false()))
    index_exists = conn.execute(
        sa.text("SELECT 1 FROM pg_indexes WHERE indexname = 'ix_checklist_is_system'")
    ).scalar()
    if not index_exists:
        op.create_index(op.f('ix_checklist_is_system'), 'checklist', ['is_system'])


def downgrade() -> None:
    op.drop_index(op.f('ix_checklist_is_system'), table_name='checklist')
    op.drop_column('checklist', 'is_system')
