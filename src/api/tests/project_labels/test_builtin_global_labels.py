"""Execute the default-label data migration against a real local SQL database."""

import importlib.util
from pathlib import Path
from types import SimpleNamespace
import sqlalchemy as sa


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
