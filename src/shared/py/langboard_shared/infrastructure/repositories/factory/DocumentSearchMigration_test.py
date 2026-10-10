"""Backfill stored transcriptions without reprocessing files or exposing deleted sources."""

import importlib.util
import json
from pathlib import Path
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, text
from ....core.types import SnowflakeID


def test_document_search_migration_projects_existing_text_and_preserves_sources(monkeypatch):
    root = Path(__file__).resolve().parents[7]
    path = root / "src/api/langboard/migrations/versions/20261006110000-6b9e17ac042d.py"
    spec = importlib.util.spec_from_file_location("document_search_migration", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    engine = create_engine("sqlite://")
    with engine.begin() as connection:
        connection.execute(
            text(
                "CREATE TABLE card_attachment (id BIGINT PRIMARY KEY, card_id BIGINT, deleted_at TIMESTAMP, original TEXT)"
            )
        )
        connection.execute(
            text("CREATE TABLE card_metadata (id BIGINT PRIMARY KEY, card_id BIGINT, key TEXT, value TEXT)")
        )
        for ident, card_id, deleted in [(1, 7, None), (2, 7, "2026-10-06"), (3, 8, None)]:
            connection.execute(
                text("INSERT INTO card_attachment VALUES (:id,:card,:deleted,'untouched-original')"),
                {"id": ident, "card": card_id, "deleted": deleted},
            )
        documents = [
            {"attachment_uid": SnowflakeID(ident).to_short_code(), "content": {"markdown": f"한글 전사 {ident}"}}
            for ident in (1, 2, 3)
        ]
        connection.execute(
            text("INSERT INTO card_metadata VALUES (1,7,'__system.docling_documents',:value)"),
            {"value": json.dumps(documents)},
        )
        connection.execute(text("INSERT INTO card_metadata VALUES (2,7,'__system.docling_documents','invalid JSON')"))
        monkeypatch.setattr(module, "op", Operations(MigrationContext.configure(connection)))
        module.upgrade()
        rows = connection.execute(text("SELECT id, document_text, original FROM card_attachment ORDER BY id")).all()
        assert rows == [
            (1, "한글 전사 1", "untouched-original"),
            (2, "", "untouched-original"),
            (3, "", "untouched-original"),
        ]
        assert connection.execute(text("SELECT COUNT(*) FROM card_metadata")).scalar() == 2
        module.downgrade()
        assert connection.execute(text("SELECT COUNT(*) FROM card_attachment")).scalar() == 3
    engine.dispose()
