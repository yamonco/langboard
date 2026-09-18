"""add card_comment section_anchor

Revision ID: e5f8b93c2d41
Revises: da39f306364b
Create Date: 2026-09-18 01:00:00.000000

"""

from typing import Sequence, Union
import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision: str = 'e5f8b93c2d41'
down_revision: Union[str, None] = 'da39f306364b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('card_comment', sa.Column('section_anchor', sa.String(length=200), nullable=True))
    op.create_index(op.f('ix_card_comment_section_anchor'), 'card_comment', ['section_anchor'])


def downgrade() -> None:
    op.drop_index(op.f('ix_card_comment_section_anchor'), table_name='card_comment')
    op.drop_column('card_comment', 'section_anchor')
