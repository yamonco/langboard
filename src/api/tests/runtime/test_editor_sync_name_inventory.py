import hashlib
import json
import sys
from collections.abc import Iterator
from contextlib import nullcontext
from pathlib import Path
from unittest.mock import MagicMock
from langboard.commands import EditorSyncNameInventoryCommand as name_inventory
from langboard_shared.core.db import DbSession
from langboard_shared.core.types import SnowflakeID
from langboard_shared.domain.models import Card, Project
from pytest import MonkeyPatch


def test_matches_only_existing_document_names(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    name = "card:known:title"
    file_name = f"{hashlib.sha256(name.encode()).hexdigest()}.ydoc"
    _ = (tmp_path / file_name).write_bytes(b"state")
    _ = (tmp_path / "unknown.ydoc").write_bytes(b"state")
    _ = (tmp_path / "interrupted.tmp").write_bytes(b"state")
    opaque_file = f"{'a' * 64}.ydoc"
    _ = (tmp_path / opaque_file).write_bytes(b"state")
    monkeypatch.setattr(name_inventory, "_candidates", lambda _db: iter((name, "card:missing:title")))

    names, opaque, unmapped = name_inventory.inventory(tmp_path, MagicMock(spec=DbSession))

    assert names == [name]
    assert opaque == [opaque_file]
    assert unmapped == ["interrupted.tmp", "unknown.ydoc"]


def test_main_allows_opaque_documents_but_rejects_unmapped_files(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    source = tmp_path / "source"
    source.mkdir()
    output = tmp_path / "names.json"
    opaque_file = f"{'a' * 64}.ydoc"
    monkeypatch.setattr(name_inventory.DbSession, "use", lambda **_kwargs: nullcontext(MagicMock(spec=DbSession)))
    monkeypatch.setattr(sys, "argv", ["inventory", str(source), str(output)])

    monkeypatch.setattr(name_inventory, "inventory", lambda _source, _db: (["card:known:title"], [opaque_file], []))
    assert name_inventory.main() == 0
    assert json.loads(output.read_text(encoding="utf-8")) == ["card:known:title"]

    monkeypatch.setattr(name_inventory, "inventory", lambda _source, _db: ([], [opaque_file], ["interrupted.tmp"]))
    assert name_inventory.main() == 1


def test_short_code_reuses_domain_uid_encoding() -> None:
    record_id = 350970103040769986
    assert name_inventory._uid(record_id) == SnowflakeID(record_id).to_short_code()


def test_candidates_include_all_static_card_and_project_documents(monkeypatch: MonkeyPatch) -> None:
    card_id = 350970103040769986
    project_id = 350970103040769987

    def rows(_db: DbSession, model: object, *_fields: str, **_kwargs: object) -> Iterator[tuple[object, ...]]:
        if model is Card:
            return iter(((card_id,),))
        if model is Project:
            return iter(((project_id,),))
        return iter(())

    monkeypatch.setattr(name_inventory, "_rows", rows)

    candidates = set(name_inventory._candidates(MagicMock(spec=DbSession)))
    card_uid = name_inventory._uid(card_id)
    project_uid = name_inventory._uid(project_id)

    assert {
        f"card:{card_uid}:title",
        f"card:{card_uid}:description",
        f"card:{card_uid}:deadline",
        f"card:{card_uid}:members",
        f"card:{card_uid}:labels",
        f"card:{card_uid}:relationships-parents",
        f"card:{card_uid}:relationships-children",
        f"board-settings:{project_uid}",
        f"board-settings:{project_uid}:members",
    } <= candidates
