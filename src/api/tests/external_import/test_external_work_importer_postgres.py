"""Real PostgreSQL contract for native card creation through external import."""

import os
from uuid import uuid4
import pytest
from pydantic import SecretStr
from sqlalchemy import create_engine, select, text


os.environ.setdefault("PROJECT_NAME", "langboard")

from langboard.external_import import ExternalWorkBundle  # noqa: E402
from langboard.external_import.importer import ExternalWorkImporter  # noqa: E402
from langboard_shared.core.db.DbEngine import DbEngine  # noqa: E402
from langboard_shared.core.db.Models import BaseDbModel  # noqa: E402
from langboard_shared.core.types import SnowflakeID  # noqa: E402
from langboard_shared.domain.models import (  # noqa: E402
    Card,
    CardAssignedProjectLabel,
    ExternalImportRecord,
    Project,
    User,
)
from langboard_shared.helpers import ensure_models_imported  # noqa: E402


DATABASE_URL = os.getenv("LANGBOARD_OUTBOX_TEST_DATABASE_URL")


@pytest.mark.skipif(not DATABASE_URL, reason="dedicated PostgreSQL proof URL not set")
def test_imported_card_shares_native_creation_invariants(monkeypatch: pytest.MonkeyPatch) -> None:
    ensure_models_imported()
    schema = f"external_import_{uuid4().hex}"
    admin = create_engine(DATABASE_URL)
    with admin.begin() as connection:
        connection.execute(text(f"CREATE SCHEMA {schema}"))
    engine = create_engine(DATABASE_URL, connect_args={"options": f"-csearch_path={schema}"})
    monkeypatch.setattr(DbEngine, "get_main_engine", lambda: engine)
    monkeypatch.setattr(DbEngine, "get_readonly_engine", lambda: engine)
    try:
        needed = {
            "user", "project", "project_column", "project_label", "project_assigned_user",
            "card", "card_assigned_user", "card_assigned_project_label", "checklist",
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
        actor_id, project_id = SnowflakeID(1001), SnowflakeID(2001)
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
        bundle = ExternalWorkBundle.model_validate({
            "schema_version": "1",
            "source": {"namespace": "tracker", "container_id": "project-1", "batch_id": "batch-1"},
            "columns": [{"source_id": "column-1", "name": "Backlog", "order": 4}],
            "labels": [{"source_id": "label-1", "name": "Imported", "color": "#112233", "order": 7}],
            "cards": [{
                "source_id": "card-1", "column_source_id": "column-1", "title": "Imported work",
                "description": "Historical description", "order": 9, "label_source_ids": ["label-1"],
            }],
        })
        importer = ExternalWorkImporter(effect_dispatcher=lambda *_args: None)
        first = importer.import_bundle(
            bundle, project_uid=project_id.to_short_code(), actor_uid=actor_id.to_short_code()
        )
        second = importer.import_bundle(
            bundle, project_uid=project_id.to_short_code(), actor_uid=actor_id.to_short_code()
        )
        assert first.created == {"column": 1, "label": 1, "card": 1}
        assert second.unchanged == {"column": 1, "label": 1, "card": 1}
        with engine.connect() as connection:
            card = connection.execute(select(Card.__table__)).mappings().one()
            assert card["created_by_user_id"] == actor_id
            assert card["last_change_seq"] > 0
            assert card["last_change_target_type"] == "card"
            assert card["order"] == 9
            assert connection.execute(select(CardAssignedProjectLabel.__table__)).one() is not None
            assert len(connection.execute(select(ExternalImportRecord.__table__)).all()) == 3
    finally:
        engine.dispose()
        with admin.begin() as connection:
            connection.execute(text(f"DROP SCHEMA IF EXISTS {schema} CASCADE"))
        admin.dispose()
