import os
from contextlib import contextmanager
from typing import Any
import pytest
import sqlalchemy as sa
from pydantic import SecretStr
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool


os.environ.setdefault("PROJECT_NAME", "langboard")

from langboard.external_import import ExternalWorkBundle  # noqa: E402
from langboard.external_import.importer import ExternalWorkImporter  # noqa: E402
from langboard_shared.core.db import DbSession  # noqa: E402
from langboard_shared.core.types import SnowflakeID  # noqa: E402
from langboard_shared.domain.models import ExternalImportRecord, Project, ProjectColumn, User  # noqa: E402


def _bundle() -> ExternalWorkBundle:
    return ExternalWorkBundle.model_validate(
        {
            "schema_version": "1",
            "source": {"namespace": "tracker", "container_id": "project-1", "batch_id": "batch-1"},
            "columns": [
                {"source_id": "column-1", "name": "Backlog", "order": 0},
                {"source_id": "column-2", "name": "Done", "order": 1},
            ],
        }
    )


def _database(monkeypatch: pytest.MonkeyPatch) -> tuple[sa.Engine, str, str]:
    engine = sa.create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    User.metadata.create_all(
        engine,
        tables=[User.__table__, Project.__table__, ProjectColumn.__table__, ExternalImportRecord.__table__],
    )
    actor_id = SnowflakeID(1001)
    project_id = SnowflakeID(2001)
    with engine.begin() as connection:
        connection.execute(
            User.__table__.insert(),
            {
                "id": actor_id,
                "firstname": "Import",
                "lastname": "Actor",
                "email": "importer@example.invalid",
                "username": "importer",
                "password": SecretStr("unused"),
                "is_admin": True,
                "preferred_lang": "en-US",
            },
        )
        connection.execute(
            Project.__table__.insert(),
            {
                "id": project_id,
                "owner_id": actor_id,
                "title": "Import target",
                "project_type": "Other",
                "archive_visible_days": 7,
            },
        )

    @contextmanager
    def use_database(*, readonly: bool):
        with Session(engine, expire_on_commit=False) as session:
            db = DbSession(session, readonly=readonly)
            if readonly:
                yield db
            else:
                with session.begin():
                    yield db

    monkeypatch.setattr(DbSession, "use", use_database)
    # These transaction-boundary tests import columns only. Relationship graph
    # validation has its own contract coverage and would require the entire card
    # schema in this deliberately minimal database fixture.
    monkeypatch.setattr(ExternalWorkImporter, "_validate_relationship_graph", lambda *_args: None)
    return engine, project_id.to_short_code(), actor_id.to_short_code()


def _counts(engine: sa.Engine) -> tuple[int, int]:
    with engine.connect() as connection:
        return (
            connection.scalar(sa.select(sa.func.count()).select_from(ProjectColumn.__table__)) or 0,
            connection.scalar(sa.select(sa.func.count()).select_from(ExternalImportRecord.__table__)) or 0,
        )


def test_partial_database_failure_resumes_without_duplicate_targets(monkeypatch: pytest.MonkeyPatch) -> None:
    engine, project_uid, actor_uid = _database(monkeypatch)
    effects: list[str] = []
    importer = ExternalWorkImporter(effect_dispatcher=lambda _kind, record, *_args: effects.append(record.source_id))
    create_target = importer._create_target

    def fail_second(db: Any, project: Any, record: Any, targets: Any, principals: Any, staged_file: Any) -> Any:
        if record.source_id == "column-2":
            raise RuntimeError("injected batch failure")
        return create_target(db, project, record, targets, principals, staged_file)

    monkeypatch.setattr(importer, "_create_target", fail_second)
    with pytest.raises(RuntimeError, match="injected batch failure"):
        importer.import_bundle(_bundle(), project_uid=project_uid, actor_uid=actor_uid)

    assert _counts(engine) == (1, 1)
    monkeypatch.setattr(importer, "_create_target", create_target)

    receipt = importer.import_bundle(_bundle(), project_uid=project_uid, actor_uid=actor_uid)

    assert receipt.created == {"column": 1}
    assert receipt.unchanged == {"column": 1}
    assert _counts(engine) == (2, 2)
    assert effects == ["column-1", "column-2"]


def test_failed_post_commit_effect_is_durably_replayed(monkeypatch: pytest.MonkeyPatch) -> None:
    engine, project_uid, actor_uid = _database(monkeypatch)
    attempts: list[str] = []

    def fail_once(_kind: str, record: Any, *_args: Any) -> None:
        attempts.append(record.source_id)
        if len(attempts) == 1:
            raise RuntimeError("injected publisher failure")

    importer = ExternalWorkImporter(effect_dispatcher=fail_once)
    payload = _bundle().model_copy(update={"columns": _bundle().columns[:1]})
    with pytest.raises(RuntimeError, match="injected publisher failure"):
        importer.import_bundle(payload, project_uid=project_uid, actor_uid=actor_uid)

    assert _counts(engine) == (1, 1)
    with engine.connect() as connection:
        pending = connection.execute(sa.select(ExternalImportRecord.__table__)).mappings().one()
    assert pending["effects_dispatched_at"] is None
    assert pending["effects_attempts"] == 1
    assert "publisher failure" in pending["effects_error"]

    receipt = importer.import_bundle(payload, project_uid=project_uid, actor_uid=actor_uid)

    assert receipt.created == {}
    assert receipt.unchanged == {"column": 1}
    assert _counts(engine) == (1, 1)
    assert attempts == ["column-1", "column-1"]
    with engine.connect() as connection:
        completed = connection.execute(sa.select(ExternalImportRecord.__table__)).mappings().one()
    assert completed["effects_dispatched_at"] is not None
    assert completed["effects_attempts"] == 2
    assert completed["effects_error"] is None
