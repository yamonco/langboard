"""A real migration preserves legacy cards privately and rejects unsafe rollback."""

import importlib.util
import os
from pathlib import Path
import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, text
from sqlalchemy.exc import IntegrityError


os.environ.setdefault("PROJECT_NAME", "langboard")


def test_visibility_migration_defaults_audits_and_rollback_guards():
    path = Path(__file__).parents[2] / "langboard/migrations/versions/20261007220000-1b392df0a6ce.py"
    spec = importlib.util.spec_from_file_location("visibility_migration", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    engine = create_engine("sqlite://")
    with engine.connect() as connection:
        connection.execute(text("PRAGMA foreign_keys=ON"))
        connection.execute(text('CREATE TABLE "user"(id BIGINT PRIMARY KEY)'))
        connection.execute(text('INSERT INTO "user" VALUES (10)'))
        connection.execute(text('CREATE TABLE bot(id BIGINT PRIMARY KEY)'))
        connection.execute(text('INSERT INTO bot VALUES (30)'))
        connection.execute(text("CREATE TABLE card(id BIGINT PRIMARY KEY, project_id BIGINT, title TEXT)"))
        connection.execute(text("INSERT INTO card VALUES (1, 100, 'Legacy')"))
        with Operations.context(MigrationContext.configure(connection)):
            module.upgrade()
        connection.execute(text("INSERT INTO card(id,project_id,title) VALUES (2,100,'New')"))
        assert connection.execute(text("SELECT visibility FROM card ORDER BY id")).scalars().all() == ["INTERNAL", "INTERNAL"]
        with pytest.raises(IntegrityError):
            connection.execute(text("UPDATE card SET visibility='UNKNOWN' WHERE id=1"))
        with Operations.context(MigrationContext.configure(connection)):
            with pytest.raises(RuntimeError, match="Internal cards"):
                module.downgrade()
        audit = text("INSERT INTO card_visibility_change VALUES (:id,CURRENT_TIMESTAMP,CURRENT_TIMESTAMP,:card,:actor,NULL,'human_ui',:previous,:next)")
        connection.execute(audit, dict(id=20, card=1, actor=10, previous="INTERNAL", next="SHARED"))
        for fields in (
            dict(id=21, card=1, actor=999, previous="INTERNAL", next="SHARED"),
            dict(id=22, card=999, actor=10, previous="INTERNAL", next="SHARED"),
            dict(id=23, card=1, actor=10, previous="INTERNAL", next="INTERNAL"),
            dict(id=24, card=1, actor=10, previous="UNKNOWN", next="SHARED"),
        ):
            with pytest.raises(IntegrityError):
                connection.execute(audit, fields)
        bot_audit = text("INSERT INTO card_visibility_change VALUES (:id,CURRENT_TIMESTAMP,CURRENT_TIMESTAMP,1,:actor,30,'bot',:previous,:next)")
        connection.execute(bot_audit, dict(id=25, actor=None, previous="SHARED", next="INTERNAL"))
        for fields in (
            dict(id=26, actor=None, previous="INTERNAL", next="SHARED"),
            dict(id=27, actor=10, previous="SHARED", next="INTERNAL"),
        ):
            with pytest.raises(IntegrityError):
                connection.execute(bot_audit, fields)
        with pytest.raises(IntegrityError):
            connection.execute(text("INSERT INTO card_visibility_change VALUES (28,CURRENT_TIMESTAMP,CURRENT_TIMESTAMP,1,10,NULL,'mcp','INTERNAL','SHARED')"))
        connection.execute(text("UPDATE card SET visibility='SHARED'"))
        with Operations.context(MigrationContext.configure(connection)):
            with pytest.raises(RuntimeError, match="audit records"):
                module.downgrade()
        assert connection.execute(text("SELECT count(*) FROM card_visibility_change")).scalar_one() == 2
        connection.execute(text("DELETE FROM card_visibility_change"))
        with Operations.context(MigrationContext.configure(connection)):
            module.downgrade()
        assert connection.execute(text("SELECT title FROM card ORDER BY id")).scalars().all() == ["Legacy", "New"]
    engine.dispose()
