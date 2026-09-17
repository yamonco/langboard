"""merge comment anchor canary head

Revision ID: 3529fe5238b9
Revises: f19c8b0d4e21, c7b0d5a6e491
Create Date: 2026-09-11 06:47:13.941060

"""

from typing import Sequence, Union


# revision identifiers, used by Alembic.
revision: str = "3529fe5238b9"
down_revision: Union[str, None] = ("f19c8b0d4e21", "c7b0d5a6e491")
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
