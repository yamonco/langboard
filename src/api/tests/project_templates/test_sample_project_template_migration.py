"""Regression contract for the built-in sample project templates."""

import importlib.util
from pathlib import Path
from types import ModuleType
import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations


ROOT = Path(__file__).resolve().parents[4]
MIGRATION = ROOT / "src/api/langboard/migrations/versions/20260807193000-7c1f0d6a2e54.py"


def _migration() -> ModuleType:
    spec = importlib.util.spec_from_file_location("sample_project_templates", MIGRATION)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _row(template_id: int, name: str, columns: list[str], *, builtin: bool, default: bool) -> dict[str, object]:
    return {
        "id": template_id,
        "name": name,
        "columns": columns,
        "internal_bots": [],
        "project_bot_scopes": [],
        "column_bot_scopes": [],
        "is_builtin": builtin,
        "is_default": default,
    }


def test_sample_catalog_is_distinct_and_keeps_archive_native() -> None:
    """Ten samples use unique one-token names and leave Archive to Project."""

    migration = _migration()
    templates = migration.SAMPLE_TEMPLATES

    assert len(templates) == 10
    assert [item[0] for item in templates] == list(range(2, 12))
    assert len({item[1] for item in templates}) == 10
    assert all(" " not in name for _, name, _ in templates)
    assert all(columns and len(columns) == len(set(columns)) for _, _, columns in templates)
    assert all("Archive" not in columns for _, _, columns in templates)


def test_seed_is_repeatable_and_preserves_same_name_user_templates() -> None:
    """Repeated seeding skips names already owned by built-ins or users."""

    migration = _migration()
    first = migration._rows_to_insert([(1, "SI"), (99, "Support")])

    assert len(first) == 9
    assert all(row["name"] != "Support" for row in first)
    assert all(row["is_builtin"] is True and row["is_default"] is False for row in first)
    assert all(row["internal_bots"] == [] for row in first)

    after_first = [(1, "SI"), (99, "Support"), *((row["id"], row["name"]) for row in first)]
    assert migration._rows_to_insert(after_first) == []


def test_seed_refuses_a_reserved_id_collision() -> None:
    """A conflicting reserved ID fails instead of silently dropping a sample."""

    migration = _migration()

    with pytest.raises(RuntimeError, match="Reserved sample project template ID is already used: 2"):
        migration._rows_to_insert([(2, "Existing user template")])


def test_upgrade_twice_preserves_existing_name_and_default() -> None:
    """The real Alembic operation is idempotent and never rewrites user rows."""

    migration = _migration()
    metadata = sa.MetaData()
    table = sa.Table(
        "project_template",
        metadata,
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("name", sa.String(), unique=True, nullable=False),
        sa.Column("columns", sa.JSON(), nullable=False),
        sa.Column("internal_bots", sa.JSON(), nullable=False),
        sa.Column("project_bot_scopes", sa.JSON(), nullable=False),
        sa.Column("column_bot_scopes", sa.JSON(), nullable=False),
        sa.Column("is_builtin", sa.Boolean(), nullable=False),
        sa.Column("is_default", sa.Boolean(), nullable=False),
    )
    engine = sa.create_engine("sqlite://")
    with engine.begin() as connection:
        metadata.create_all(connection)
        connection.execute(
            table.insert(),
            [
                _row(1, "SI", ["Backlog", "Done"], builtin=True, default=False),
                _row(99, "Support", ["Custom"], builtin=False, default=False),
                _row(100, "My-Default", ["Only"], builtin=False, default=True),
            ],
        )
        migration.op = Operations(MigrationContext.configure(connection))
        migration.upgrade()
        migration.upgrade()
        rows = connection.execute(sa.select(table).order_by(table.c.id)).mappings().all()

    assert len(rows) == 12
    support = next(row for row in rows if row["name"] == "Support")
    assert support["columns"] == ["Custom"] and support["is_builtin"] is False
    assert [row["name"] for row in rows if row["is_default"]] == ["My-Default"]
