"""merge smart project activity into canary

Revision ID: 404967cb79df
Revises: 8a9f1a5a9599, 57c4d82e1a63
Create Date: 2026-09-11 07:17:53.331447

"""

from typing import Sequence, Union


# revision identifiers, used by Alembic.
revision: str = '404967cb79df'
down_revision: Union[str, None] = ('8a9f1a5a9599', '57c4d82e1a63')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
