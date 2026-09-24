"""Real PostgreSQL contract for native card creation through external import."""

import os
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from uuid import uuid4
import pytest
from pydantic import SecretStr
from sqlalchemy import create_engine, select, text


os.environ.setdefault("PROJECT_NAME", "langboard")

from langboard.external_import import ExternalWorkBundle  # noqa: E402
from langboard.external_import.importer import ExternalWorkImporter  # noqa: E402
from langboard_shared.core.db.DbEngine import DbEngine  # noqa: E402
from langboard_shared.core.db.Models import BaseDbModel  # noqa: E402
from langboard_shared.core.storage import Storage  # noqa: E402
from langboard_shared.core.storage.LocalStorage import LocalStorage  # noqa: E402
from langboard_shared.core.types import SnowflakeID  # noqa: E402
from langboard_shared.domain.models import (  # noqa: E402
    Card,
    CardAssignedProjectLabel,
    CardAttachment,
    CardComment,
    CardRelationship,
    Checkitem,
    Checklist,
    ExternalImportRecord,
    GlobalCardRelationshipType,
    Project,
    ProjectAssignedUser,
    ProjectColumn,
    ProjectLabel,
    User,
    UserIdentityLink,
)
from langboard_shared.domain.models.UserIdentityLink import IdentityProvider  # noqa: E402
from langboard_shared.Env import Env  # noqa: E402
from langboard_shared.helpers import ensure_models_imported  # noqa: E402
from langboard_shared.publishers import CardAttachmentPublisher  # noqa: E402
from langboard_shared.tasks.activities import CardAttachmentActivityTask  # noqa: E402
from langboard_shared.tasks.bots import CardAttachmentBotTask  # noqa: E402


DATABASE_URL = os.getenv("LANGBOARD_OUTBOX_TEST_DATABASE_URL")


@pytest.mark.skipif(not DATABASE_URL, reason="dedicated PostgreSQL proof URL not set")
def test_imported_card_shares_native_creation_invariants(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    ensure_models_imported()
    monkeypatch.setattr(type(Env), "SCIM_ISSUER", property(lambda _self: "test-issuer"))
    monkeypatch.setattr(type(Env), "LOCAL_STORAGE_DIR", property(lambda _self: tmp_path / "storage"))
    monkeypatch.setattr(Storage, "_storages", {"local": LocalStorage()})
    attachments_root = tmp_path / "bundle"
    attachments_root.mkdir()
    attachment_bytes = b"historical attachment\n"
    (attachments_root / "note.txt").write_bytes(attachment_bytes)
    schema = f"external_import_{uuid4().hex}"
    admin = create_engine(DATABASE_URL)
    with admin.begin() as connection:
        connection.execute(text(f"CREATE SCHEMA {schema}"))
    engine = create_engine(DATABASE_URL, connect_args={"options": f"-csearch_path={schema}"})
    monkeypatch.setattr(DbEngine, "get_main_engine", lambda: engine)
    monkeypatch.setattr(DbEngine, "get_readonly_engine", lambda: engine)
    try:
        needed = {
            "user", "user_identity_link", "project", "project_column", "project_label", "project_assigned_user",
            "card", "card_assigned_user", "card_assigned_project_label", "card_attachment", "card_comment", "checklist",
            "checkitem", "external_import_record", "project_execution_binding",
            "webhook_setting", "card_relationship",
        }
        while True:
            previous = len(needed)
            for name in list(needed):
                needed.update(fk.column.table.name for fk in BaseDbModel.metadata.tables[name].foreign_keys)
            if len(needed) == previous:
                break
        BaseDbModel.metadata.create_all(engine, tables=[BaseDbModel.metadata.tables[name] for name in needed])
        actor_id, project_id, relationship_type_id = SnowflakeID(1001), SnowflakeID(2001), SnowflakeID(3001)
        with engine.begin() as connection:
            connection.execute(text("CREATE SEQUENCE content_change_seq"))
            connection.execute(text(
                "CREATE TABLE card_execution_generation "
                "(card_id bigint PRIMARY KEY REFERENCES card(id), execution_generation integer NOT NULL DEFAULT 0)"
            ))
            connection.execute(User.__table__.insert(), {
                "id": actor_id, "firstname": "Import", "lastname": "Actor",
                "email": "importer@example.invalid", "username": "importer",
                "password": SecretStr("unused"), "is_admin": True, "preferred_lang": "en-US",
            })
            connection.execute(Project.__table__.insert(), {
                "id": project_id, "owner_id": actor_id, "title": "Import target",
                "project_type": "Other", "archive_visible_days": 7,
            })
            connection.execute(GlobalCardRelationshipType.__table__.insert(), {
                "id": relationship_type_id, "parent_name": "blocks", "child_name": "blocked by", "description": "",
            })
            connection.execute(ProjectAssignedUser.__table__.insert(), {
                "id": SnowflakeID(4001), "project_id": project_id, "user_id": actor_id, "starred": False,
            })
            connection.execute(UserIdentityLink.__table__.insert(), {
                "id": SnowflakeID(5001), "user_id": actor_id, "provider": IdentityProvider.Scim,
                "external_id": "scim-actor", "issuer": "test-issuer",
            })
        comment_time = datetime(2020, 1, 2, 3, 4, tzinfo=timezone.utc)
        bundle = ExternalWorkBundle.model_validate({
            "schema_version": "1",
            "source": {"namespace": "tracker", "container_id": "project-1", "batch_id": "batch-1"},
            "columns": [
                {"source_id": "column-1", "name": "Backlog", "order": 4},
                {"source_id": "column-2", "name": "Done", "order": 8},
            ],
            "labels": [
                {"source_id": "label-1", "name": "Imported", "color": "#112233", "order": 7},
                {"source_id": "label-2", "name": "Urgent", "color": "#aa0000", "order": 11},
            ],
            "cards": [
                {
                    "source_id": "card-1", "column_source_id": "column-1", "title": "Imported work",
                    "description": "", "order": 9, "label_source_ids": ["label-1"],
                },
                {"source_id": "card-2", "column_source_id": "column-1", "title": "Dependent work", "order": 10},
            ],
            "checklists": [
                {"source_id": "checklist-1", "card_source_id": "card-1", "title": "Imported checks", "order": 3},
                {"source_id": "checklist-2", "card_source_id": "card-1", "title": "Later checks", "order": 6},
            ],
            "checkitems": [
                {
                    "source_id": "item-1", "checklist_source_id": "checklist-1", "title": "Imported item",
                    "order": 5, "is_checked": True,
                },
                {
                    "source_id": "item-2", "checklist_source_id": "checklist-1", "title": "Later item",
                    "order": 8,
                },
            ],
            "relationships": [{
                "source_id": "edge-1", "parent_card_source_id": "card-1", "child_card_source_id": "card-2",
                "relationship_type_uid": relationship_type_id.to_short_code(),
            }],
            "comments": [{
                "source_id": "comment-1", "card_source_id": "card-1",
                "author_scim_external_id": "scim-actor", "created_at": comment_time.isoformat(),
                "content": "Historical discussion",
            }],
            "attachments": [{
                "source_id": "attachment-1", "card_source_id": "card-1",
                "author_scim_external_id": "scim-actor", "created_at": comment_time.isoformat(),
                "relative_path": "note.txt", "original_filename": "note.txt",
                "sha256": sha256(attachment_bytes).hexdigest(), "size": len(attachment_bytes),
            }],
        })
        effects: list[str] = []
        monkeypatch.setattr(CardAttachmentPublisher, "uploaded", lambda *_args: effects.append("published"))
        monkeypatch.setattr(
            CardAttachmentActivityTask, "card_attachment_uploaded", lambda *_args: effects.append("activity")
        )
        monkeypatch.setattr(
            CardAttachmentBotTask, "card_attachment_uploaded",
            lambda *_args: pytest.fail("historical attachment dispatched a live bot"),
        )
        importer = ExternalWorkImporter(attachments_root)
        native_dispatch = importer._effect_dispatcher
        importer._effect_dispatcher = lambda kind, *args: native_dispatch(kind, *args) if kind == "attachment" else None
        first = importer.import_bundle(
            bundle, project_uid=project_id.to_short_code(), actor_uid=actor_id.to_short_code()
        )
        second = importer.import_bundle(
            bundle, project_uid=project_id.to_short_code(), actor_uid=actor_id.to_short_code()
        )
        expected = {
            "column": 2, "label": 2, "card": 2, "checklist": 2, "checkitem": 2,
            "relationship": 1, "comment": 1, "attachment": 1,
        }
        assert first.created == expected
        assert second.unchanged == expected
        assert effects == ["published", "activity"]
        with engine.connect() as connection:
            card = connection.execute(select(Card.__table__).where(Card.title == "Imported work")).mappings().one()
            dependent = connection.execute(select(Card.__table__).where(Card.title == "Dependent work")).mappings().one()
            assert card["created_by_user_id"] == actor_id
            assert card["last_change_seq"] > 0
            assert card["last_change_target_type"] == "attachment"
            assert card["order"] == 9
            assert dependent["order"] == 10
            assert connection.execute(select(CardAssignedProjectLabel.__table__)).one() is not None
            assert {
                row["name"]: row["order"]
                for row in connection.execute(select(ProjectColumn.__table__)).mappings()
            } == {"Backlog": 4, "Done": 8}
            assert {
                row["name"]: row["order"]
                for row in connection.execute(select(ProjectLabel.__table__)).mappings()
            } == {"Imported": 7, "Urgent": 11}
            checklists = connection.execute(
                select(Checklist.__table__).where(
                    Checklist.deleted_at.is_(None), Checklist.card_id == card["id"]
                )
            ).mappings().all()
            assert {row["title"]: row["order"] for row in checklists} == {
                "Imported checks": 3, "Later checks": 6,
            }
            assert all(row["is_system"] is False for row in checklists)
            imported_checklist = next(row for row in checklists if row["title"] == "Imported checks")
            items = connection.execute(
                select(Checkitem.__table__).where(Checkitem.checklist_id == imported_checklist["id"])
            ).mappings().all()
            assert {row["title"]: (row["order"], row["is_checked"]) for row in items} == {
                "Imported item": (5, True), "Later item": (8, False),
            }
            edge = connection.execute(select(CardRelationship.__table__)).mappings().one()
            assert (edge["card_id_parent"], edge["card_id_child"], edge["relationship_type_id"]) == (
                card["id"], dependent["id"], relationship_type_id
            )
            comment = connection.execute(select(CardComment.__table__)).mappings().one()
            assert comment["card_id"] == card["id"]
            assert comment["user_id"] == actor_id
            assert comment["created_at"] == comment_time
            assert comment["content"].content == "Historical discussion"
            attachment = connection.execute(select(CardAttachment.__table__)).mappings().one()
            assert attachment["card_id"] == card["id"]
            assert attachment["user_id"] == actor_id
            assert attachment["created_at"] == comment_time
            assert attachment["filename"] == "note.txt"
            assert Storage.get_file(attachment["file"]) == attachment_bytes
            assert len(connection.execute(select(ExternalImportRecord.__table__)).all()) == 13
    finally:
        engine.dispose()
        with admin.begin() as connection:
            connection.execute(text(f"DROP SCHEMA IF EXISTS {schema} CASCADE"))
        admin.dispose()
