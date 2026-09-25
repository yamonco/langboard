"""merge canary completion checklist and content-block heads

Revision ID: d7e8a1c29f04
Revises: f2b8d0e41c76, a91c4d2e7f10
Create Date: 2026-09-20 05:45:00.000000

"""

from typing import Sequence, Union


revision: str = "d7e8a1c29f04"
down_revision: Union[str, Sequence[str], None] = ("f2b8d0e41c76", "a91c4d2e7f10")
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
