"""merge canary feature heads

Revision ID: f19c8b0d4e21
Revises: 3a6f8c1d2e4b, 54e9c7a1d230, 4e8b1c7d2a90, c3f9a2e7d410,
    7b7818743022, ffefabc64037
Create Date: 2026-09-11 09:00:00
"""

from collections.abc import Sequence


revision: str = "f19c8b0d4e21"
down_revision: tuple[str, ...] = (
    "3a6f8c1d2e4b",
    "54e9c7a1d230",
    "4e8b1c7d2a90",
    "c3f9a2e7d410",
    "7b7818743022",
    "ffefabc64037",
)
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
