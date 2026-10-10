"""merge external import checkpoint repair into canary

Revision ID: 8a9f1a5a9599
Revises: 3529fe5238b9, 7c9e1ad4f620
Create Date: 2026-09-11 07:09:27.099243

"""

from typing import Sequence, Union


# revision identifiers, used by Alembic.
revision: str = '8a9f1a5a9599'
down_revision: Union[str, None] = ('3529fe5238b9', '7c9e1ad4f620')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
