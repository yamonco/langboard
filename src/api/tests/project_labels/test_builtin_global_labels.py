"""Execute the default-label data migration against a real local SQL database."""

import importlib.util
import os
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4
import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations
from langboard_shared.core.types import SnowflakeID


def migration():
    path = Path(__file__).parents[2] / "langboard/migrations/versions/20261002081000-28d93ec602b1.py"
    spec = importlib.util.spec_from_file_location("builtin_global_labels", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_defaults_are_multilingual_work_types():
    module = migration()
    rows = module._rows_to_insert([])
    assert module.down_revision == "17c82db591a0"
    assert len(rows) == 13
    assert len({row["id"] for row in rows}) == 13
    assert {row["name"] for row in rows} == {
        "Bug",
        "Feature",
        "Improvement",
        "Documentation",
        "Security",
        "Maintenance",
        "Frontend",
        "Backend",
        "Contract",
        "Assembly",
        "Question",
        "Money",
        "Pricing",
    }
    for row in rows:
        assert set(row["translations"]) == {"en", "ko", "ja", "zh"}
        assert row["translations"]["en"] == {"name": row["name"], "description": row["description"]}
        assert all(text["name"] and text["description"] for text in row["translations"].values())
        assert len(row["color"]) == 7 and row["color"].startswith("#")
        assert row["emoji"]


def test_upgrade_is_idempotent_and_preserves_existing_definitions(monkeypatch):
    module = migration()
    engine = sa.create_engine("sqlite://")
    metadata = sa.MetaData()
    table = sa.Table(
        "global_label",
        metadata,
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("created_at", sa.DateTime()),
        sa.Column("updated_at", sa.DateTime()),
        sa.Column("name", sa.String(), unique=True),
        sa.Column("color", sa.String()),
        sa.Column("description", sa.String()),
        sa.Column("translations", sa.JSON()),
    )
    metadata.create_all(engine)
    with engine.begin() as connection:
        existing = {
            "id": 1,
            "name": "bug",
            "color": "#123456",
            "description": "User definition",
            "translations": {"en": {"name": "bug"}},
        }
        connection.execute(table.insert(), existing)
        monkeypatch.setattr(
            module,
            "op",
            SimpleNamespace(
                get_bind=lambda: connection,
                add_column=lambda *args: connection.execute(
                    sa.text("ALTER TABLE global_label ADD COLUMN emoji VARCHAR NOT NULL DEFAULT ''")
                ),
                bulk_insert=lambda table, rows: connection.execute(table.insert(), rows),
            ),
        )
        module.upgrade()
        before = list(connection.execute(sa.select(table)).mappings())
        module.seed_defaults()
        after = list(connection.execute(sa.select(table)).mappings())
        assert after == before
        assert len(after) == 13
        preserved = next(row for row in after if row["id"] == 1)
        for key, value in existing.items():
            assert preserved[key] == value


def test_development_contract_and_money_pricing_boundaries_are_explicit():
    rows = {row["name"]: row for row in migration()._rows_to_insert([])}
    assert "not a legal or commercial agreement" in rows["Contract"]["description"]
    assert "법률·상거래 계약" in rows["Contract"]["translations"]["ko"]["description"]
    assert "never authorizes a payment" in rows["Money"]["description"]
    assert "billing rules" in rows["Pricing"]["description"]


def test_seed_ids_reject_existing_and_batch_collisions(monkeypatch):
    module = migration()
    candidates = iter([1, 1, 2, 2, *range(3, 15)])
    monkeypatch.setattr(module, "SnowflakeID", lambda: next(candidates))
    rows = module._rows_to_insert([], {1})
    assert [row["id"] for row in rows] == list(range(2, 15))


def test_seed_allocation_exhaustion_does_not_insert_partial_rows(monkeypatch):
    module = migration()
    writes = []
    connection = SimpleNamespace(execute=lambda query: [SimpleNamespace(id=1, name="Custom")])
    monkeypatch.setattr(
        module, "op", SimpleNamespace(get_bind=lambda: connection, bulk_insert=lambda *args: writes.append(args))
    )
    monkeypatch.setattr(module, "SnowflakeID", lambda: 1)
    with pytest.raises(RuntimeError, match="allocation exhausted"):
        module.seed_defaults()
    assert not writes


@pytest.fixture(params=["sqlite", "postgresql"])
def seed_engine(request):
    admin = None
    schema = None
    if request.param == "postgresql":
        url = os.getenv("LANGBOARD_TEST_DATABASE_URL")
        if not url:
            pytest.skip("Dedicated PostgreSQL proof URL not set")
        admin = sa.create_engine(url)
        schema = f"label_seed_{uuid4().hex}"
        with admin.begin() as connection:
            connection.execute(sa.text(f"CREATE SCHEMA {schema}"))
        engine = sa.create_engine(url, connect_args={"options": f"-csearch_path={schema}"})
    else:
        engine = sa.create_engine("sqlite://")
    metadata = sa.MetaData()
    sa.Table(
        "global_label",
        metadata,
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True)),
        sa.Column("updated_at", sa.DateTime(timezone=True)),
        sa.Column("name", sa.String(), unique=True, nullable=False),
        sa.Column("color", sa.String(), nullable=False),
        sa.Column("description", sa.String()),
        sa.Column("emoji", sa.String()),
        sa.Column("translations", sa.JSON()),
    )
    metadata.create_all(engine)
    try:
        yield engine
    finally:
        engine.dispose()
        if admin:
            with admin.begin() as connection:
                connection.execute(sa.text(f"DROP SCHEMA {schema} CASCADE"))
            admin.dispose()


def test_native_seed_transaction_rolls_back_partial_write_and_retries(monkeypatch, seed_engine):
    module = migration()
    table = module.global_label
    custom = {
        "id": 1,
        "name": "bug",
        "color": "#123456",
        "description": "User definition",
        "emoji": "",
        "translations": {"en": {"name": "bug"}},
    }
    with seed_engine.begin() as connection:
        connection.execute(table.insert(), custom)

    # Execute Alembic's real bulk insert, then force a later non-PK constraint failure.
    # The migration transaction must remove the successfully inserted first row too.
    with pytest.raises(sa.exc.IntegrityError):
        with seed_engine.begin() as connection:
            native = Operations(MigrationContext.configure(connection))

            def interrupted_bulk_insert(seed_table, rows):
                native.bulk_insert(seed_table, rows[:1])
                native.bulk_insert(seed_table, [{**rows[1], "name": "bug"}])

            monkeypatch.setattr(
                module, "op", SimpleNamespace(get_bind=lambda: connection, bulk_insert=interrupted_bulk_insert)
            )
            module.seed_defaults()

    with seed_engine.begin() as connection:
        assert list(connection.execute(sa.select(table.c.name)).scalars()) == ["bug"]
        monkeypatch.setattr(module, "op", Operations(MigrationContext.configure(connection)))
        module.seed_defaults()
        before = list(connection.execute(sa.select(table).order_by(table.c.id)).mappings())
        module.seed_defaults()
        assert list(connection.execute(sa.select(table).order_by(table.c.id)).mappings()) == before
        assert len(before) == 13
        assert len({row["id"] for row in before}) == 13
        preserved = next(row for row in before if row["id"] == 1)
        assert all(preserved[key] == value for key, value in custom.items())
        assert all(set(row["translations"]) == {"en", "ko", "ja", "zh"} for row in before if row["id"] != 1)


def test_native_seed_skips_occupied_worker_sequence_range(monkeypatch, seed_engine):
    module = migration()
    monkeypatch.setattr(SnowflakeID, "_last_timestamp", -1)
    monkeypatch.setattr(SnowflakeID, "_sequence", 0)
    monkeypatch.setattr(SnowflakeID, "_machine_id", 950)
    monkeypatch.setattr(SnowflakeID, "_current_millis", classmethod(lambda cls: cls.EPOCH + 100000))
    custom = [
        {"id": int(SnowflakeID()), "name": f"Custom {index}", "color": "#123456"} for index in range(64)
    ]
    with seed_engine.begin() as connection:
        connection.execute(module.global_label.insert(), custom)
        monkeypatch.setattr(SnowflakeID, "_last_timestamp", -1)
        monkeypatch.setattr(SnowflakeID, "_sequence", 0)
        monkeypatch.setattr(module, "op", Operations(MigrationContext.configure(connection)))
        module.seed_defaults()
        rows = list(connection.execute(sa.select(module.global_label)).mappings())
        assert len(rows) == 77
        assert len({row["id"] for row in rows}) == 77
        assert all(row["id"] >> 22 == 100001 for row in rows if not row["name"].startswith("Custom "))
        module.seed_defaults()
        assert connection.execute(sa.select(sa.func.count()).select_from(module.global_label)).scalar_one() == 77
