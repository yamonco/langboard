"""Exercise direct SQL bypasses and rollback against a real migrated database."""

import importlib.util
from pathlib import Path
import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, text
from sqlalchemy.exc import IntegrityError


def test_private_ownership_survives_direct_sql_and_rollback():
    path = Path(__file__).parents[2] / "langboard/migrations/versions/20261007230000-3d5a71e8c942.py"
    spec = importlib.util.spec_from_file_location("private_migration", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    engine = create_engine("sqlite://")
    with engine.connect() as connection:
        connection.execute(text("PRAGMA foreign_keys=ON"))
        connection.execute(text('CREATE TABLE "user"(id BIGINT PRIMARY KEY)'))
        connection.execute(text('INSERT INTO "user" VALUES (10),(20)'))
        connection.execute(text("CREATE TABLE card(id BIGINT PRIMARY KEY, project_id BIGINT, title TEXT, "
                                "created_by_user_id BIGINT, created_by_bot_id BIGINT, "
                                "visibility TEXT NOT NULL DEFAULT 'INTERNAL', "
                                "CONSTRAINT card_visibility CHECK (visibility IN ('INTERNAL','SHARED')))"))
        connection.execute(text("INSERT INTO card(id,title) VALUES(1,'Legacy')"))
        with Operations.context(MigrationContext.configure(connection)):
            migration.upgrade()
        assert connection.execute(text("SELECT visibility,owner_user_id FROM card WHERE id=1")).one() == ("INTERNAL", None)
        for owner, creator, bot, visibility in (
            (None, 10, None, "PRIVATE"), (10, None, None, "PRIVATE"),
            (10, 20, None, "PRIVATE"), (10, 10, 30, "PRIVATE"),
            (999, 999, None, "PRIVATE"), (0, 0, None, "PRIVATE"),
            (10, 10, None, "INTERNAL"), (10, 10, None, "SHARED"),
        ):
            with pytest.raises(IntegrityError):
                connection.execute(text("INSERT INTO card(id,title,visibility,owner_user_id,created_by_user_id,created_by_bot_id) "
                                        "VALUES(2,'Invalid',:visibility,:owner,:creator,:bot)"),
                                   dict(visibility=visibility, owner=owner, creator=creator, bot=bot))
        connection.execute(text("INSERT INTO card(id,title,visibility,owner_user_id,created_by_user_id) VALUES(2,'Vault','PRIVATE',10,10)"))
        for statement in (
            "UPDATE card SET visibility='INTERNAL',owner_user_id=NULL WHERE id=2",
            "UPDATE card SET visibility='SHARED',owner_user_id=NULL WHERE id=2",
            "UPDATE card SET owner_user_id=20,created_by_user_id=20 WHERE id=2",
            "UPDATE card SET created_by_user_id=20 WHERE id=2",
            "UPDATE card SET created_by_bot_id=30 WHERE id=2",
            "UPDATE card SET visibility='PRIVATE',owner_user_id=10,created_by_user_id=10 WHERE id=1",
        ):
            with pytest.raises(IntegrityError):
                connection.execute(text(statement))
        connection.execute(text("UPDATE card SET title='Edited' WHERE id=2"))
        connection.execute(text("UPDATE card SET visibility='SHARED' WHERE id=1"))
        with Operations.context(MigrationContext.configure(connection)):
            with pytest.raises(RuntimeError, match="PRIVATE cards"):
                migration.downgrade()
        assert connection.execute(text("SELECT title,owner_user_id FROM card WHERE id=2")).one() == ("Edited", 10)
        connection.execute(text("DELETE FROM card WHERE id=2"))
        with Operations.context(MigrationContext.configure(connection)):
            migration.downgrade()
        assert connection.execute(text("SELECT title,visibility FROM card WHERE id=1")).one() == ("Legacy", "SHARED")
    engine.dispose()
