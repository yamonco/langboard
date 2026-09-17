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
down_revision: Union[str, None] = 'da39f306364b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('checklist', sa.Column('is_system', sa.Boolean(), nullable=False, server_default=sa.false()))
    op.create_index(op.f('ix_checklist_is_system'), 'checklist', ['is_system'])


def downgrade() -> None:
    op.drop_index(op.f('ix_checklist_is_system'), table_name='checklist')
    op.drop_column('checklist', 'is_system')
