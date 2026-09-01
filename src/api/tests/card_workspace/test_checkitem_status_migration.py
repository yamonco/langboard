"""Regression contract for legacy checkitem enum storage."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[4]
MIGRATION = (
    ROOT
    / "src/api/langboard/migrations/versions/20260806132500-a4c79b2e1d63.py"
)


def test_checkitem_status_migration_matches_enum_like_varchar_storage() -> None:
    """Both historical enum columns must converge on current varchar storage."""

    source = MIGRATION.read_text(encoding="utf-8")

    assert 'down_revision: Union[str, None] = "09fd3bc91042"' in source
    assert source.count("TYPE VARCHAR USING status::text") == 2
    assert 'op.execute("DROP TYPE IF EXISTS checkitemstatus")' in source
    assert source.count("::checkitemstatus") == 2
