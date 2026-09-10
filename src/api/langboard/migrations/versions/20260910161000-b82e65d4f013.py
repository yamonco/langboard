"""merge external import and activity recency heads

Revision ID: b82e65d4f013
Revises: 54e9c7a1d230, a71d54c3e902
Create Date: 2026-09-10 16:10:00
"""

from collections.abc import Sequence


revision: str = "b82e65d4f013"
down_revision: tuple[str, str] = ("54e9c7a1d230", "a71d54c3e902")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
