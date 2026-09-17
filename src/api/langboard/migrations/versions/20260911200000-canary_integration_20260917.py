"""merge canary integration migration heads

Revision ID: canary_integration_20260917
Revises: 404967cb79df, 4e8b1c7d2a90, 57c4d82e1a63, 7b7818743022, 7c9e1ad4f620, a3d9f6c27b41, b82e65d4f013, c7b0d5a6e491, ffefabc64037
Create Date: 2026-09-17 02:00:00.000000

"""

from collections.abc import Sequence


revision: str = "canary_integration_20260917"
down_revision: tuple[str, ...] = (
    "404967cb79df",
    "4e8b1c7d2a90",
    "57c4d82e1a63",
    "7b7818743022",
    "7c9e1ad4f620",
    "a3d9f6c27b41",
    "b82e65d4f013",
    "c7b0d5a6e491",
    "ffefabc64037",
)
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Converge independently reviewed canary migrations onto one head."""


def downgrade() -> None:
    """Return to the independent canary branch heads."""
