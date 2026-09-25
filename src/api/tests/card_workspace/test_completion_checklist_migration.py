import importlib.util
from pathlib import Path
import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy.exc import IntegrityError


MIGRATION_PATH = Path(__file__).parents[2] / "langboard" / "migrations" / "versions" / "20260920053000-a91c4d2e7f10.py"


def _migration() -> object:
    spec = importlib.util.spec_from_file_location("completion_checklist_constraint", MIGRATION_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_migration_deduplicates_and_constrains_active_system_checklists() -> None:
    engine = sa.create_engine("sqlite:///:memory:")
    with engine.begin() as connection:
        connection.execute(
            sa.text(
                """
                CREATE TABLE checklist (
                    id INTEGER PRIMARY KEY,
                    card_id INTEGER NOT NULL,
                    is_system BOOLEAN NOT NULL,
                    deleted_at DATETIME NULL
                )
                """
            )
        )
        connection.execute(
            sa.text(
                """
                INSERT INTO checklist (id, card_id, is_system, deleted_at)
                VALUES (1, 7, true, NULL), (2, 7, true, NULL), (3, 7, false, NULL)
                """
            )
        )

        module = _migration()
        module.op = Operations(MigrationContext.configure(connection))
        module.upgrade()

        active_system_ids = connection.execute(
            sa.text(
                "SELECT id FROM checklist WHERE card_id = 7 AND is_system = true AND deleted_at IS NULL ORDER BY id"
            )
        ).scalars()
        assert list(active_system_ids) == [1]

        with pytest.raises(IntegrityError):
            connection.execute(
                sa.text("INSERT INTO checklist (id, card_id, is_system, deleted_at) VALUES (4, 7, true, NULL)")
            )
        connection.execute(
            sa.text("INSERT INTO checklist (id, card_id, is_system, deleted_at) VALUES (5, 7, false, NULL)")
        )

        module.downgrade()
        index_names = {index["name"] for index in sa.inspect(connection).get_indexes("checklist")}
        assert "uq_checklist_active_system_card" not in index_names
