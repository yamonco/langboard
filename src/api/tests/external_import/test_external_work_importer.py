import os
from contextlib import contextmanager
from types import SimpleNamespace
from typing import Any
import pytest
import sqlalchemy as sa
from pydantic import SecretStr
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool


os.environ.setdefault("PROJECT_NAME", "langboard")

from langboard.external_import import ExternalWorkBundle  # noqa: E402
from langboard.external_import.importer import ExternalImportError, ExternalWorkImporter  # noqa: E402
from langboard_shared.core.db import DbSession  # noqa: E402
from langboard_shared.core.types import SnowflakeID  # noqa: E402
from langboard_shared.domain.models import (  # noqa: E402
    ExternalImportRecord,
    Project,
    ProjectAssignedUser,
    ProjectColumn,
    ProjectLabel,
    User,
    UserIdentityLink,
)
from langboard_shared.domain.models.UserIdentityLink import IdentityProvider  # noqa: E402
from langboard_shared.Env import Env  # noqa: E402


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
        tables=[
            User.__table__,
            Project.__table__,
            ProjectColumn.__table__,
            ProjectLabel.__table__,
            ExternalImportRecord.__table__,
            ProjectAssignedUser.__table__,
            UserIdentityLink.__table__,
        ],
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
        active = DbSession._atomic_session.get()
        if active is not None:
            yield active
            return
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


def test_principal_resolution_batches_users_and_preserves_membership_gate(monkeypatch: pytest.MonkeyPatch) -> None:
    engine, project_uid, _actor_uid = _database(monkeypatch)
    monkeypatch.setattr(type(Env), "SCIM_ISSUER", property(lambda _self: "test-issuer"))
    project_id = SnowflakeID.from_short_code(project_uid)
    with engine.begin() as connection:
        for index in (1, 2, 3):
            user_id = SnowflakeID(1001 + index)
            connection.execute(
                User.__table__.insert(),
                {
                    "id": user_id,
                    "firstname": "Import",
                    "lastname": f"Person {index}",
                    "email": f"person-{index}@example.invalid",
                    "username": f"person-{index}",
                    "password": SecretStr("unused"),
                    "is_admin": False,
                    "preferred_lang": "en-US",
                },
            )
            connection.execute(
                UserIdentityLink.__table__.insert(),
                {
                    "id": SnowflakeID(5000 + index),
                    "user_id": user_id,
                    "provider": IdentityProvider.Scim,
                    "external_id": f"scim-{index}",
                    "issuer": "test-issuer",
                },
            )
            if index < 3:
                connection.execute(
                    ProjectAssignedUser.__table__.insert(),
                    {
                        "id": SnowflakeID(4000 + index),
                        "project_id": project_id,
                        "user_id": user_id,
                        "starred": False,
                    },
                )
    bundle = SimpleNamespace(
        cards=[SimpleNamespace(assignee_scim_external_ids=["scim-1", "scim-2"])],
        comments=[],
        attachments=[],
    )
    statements: list[str] = []

    def count_select(
        _connection: Any, _cursor: Any, statement: str, _parameters: Any, _context: Any, _many: Any
    ) -> None:
        if statement.lstrip().upper().startswith("SELECT"):
            statements.append(statement)

    sa.event.listen(engine, "before_cursor_execute", count_select)
    try:
        with DbSession.use(readonly=True) as db:
            project = ExternalWorkImporter._require_uid(db, Project, project_uid, "project")
            statements.clear()
            principals = ExternalWorkImporter._resolve_principals(db, project, bundle)
            assert len(statements) == 2
            assert {key: user.id for key, (user, _membership) in principals.items()} == {
                "scim-1": SnowflakeID(1002),
                "scim-2": SnowflakeID(1003),
            }
            bundle.comments = [SimpleNamespace(author_scim_external_id="scim-3")]
            with pytest.raises(ExternalImportError, match="not an active project member"):
                ExternalWorkImporter._resolve_principals(db, project, bundle)
    finally:
        sa.event.remove(engine, "before_cursor_execute", count_select)


@pytest.mark.parametrize("failure_index, persisted", [(2, 0), (26, 25)])
def test_partial_database_failure_resumes_without_duplicate_targets(
    monkeypatch: pytest.MonkeyPatch, failure_index: int, persisted: int
) -> None:
    engine, project_uid, actor_uid = _database(monkeypatch)
    payload = _bundle().model_dump()
    payload["columns"] = [
        {"source_id": f"column-{index}", "name": f"Column {index}", "order": index - 1} for index in range(1, 27)
    ]
    bundle = ExternalWorkBundle.model_validate(payload)
    effects: list[str] = []
    importer = ExternalWorkImporter(effect_dispatcher=lambda _kind, record, *_args: effects.append(record.source_id))
    create_target = importer._create_target

    def fail_second(
        db: Any, project: Any, actor: Any, record: Any, targets: Any, principals: Any, staged_file: Any
    ) -> Any:
        if record.source_id == f"column-{failure_index}":
            raise RuntimeError("injected batch failure")
        return create_target(db, project, actor, record, targets, principals, staged_file)

    monkeypatch.setattr(importer, "_create_target", fail_second)
    with pytest.raises(RuntimeError, match="injected batch failure"):
        importer.import_bundle(bundle, project_uid=project_uid, actor_uid=actor_uid)

    assert _counts(engine) == (persisted, persisted)
    monkeypatch.setattr(importer, "_create_target", create_target)

    receipt = importer.import_bundle(bundle, project_uid=project_uid, actor_uid=actor_uid)

    assert receipt.created == {"column": 26 - persisted}
    assert receipt.unchanged == ({"column": persisted} if persisted else {})
    assert _counts(engine) == (26, 26)
    assert effects == [f"column-{index}" for index in range(1, 27)]


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


def test_native_column_create_and_lineage_share_one_transaction(monkeypatch: pytest.MonkeyPatch) -> None:
    engine, project_uid, actor_uid = _database(monkeypatch)
    original_insert = DbSession.insert

    def fail_lineage(db: DbSession, model: Any) -> Any:
        if isinstance(model, ExternalImportRecord):
            raise RuntimeError("lineage write failed")
        return original_insert(db, model)

    monkeypatch.setattr(DbSession, "insert", fail_lineage)
    importer = ExternalWorkImporter(effect_dispatcher=lambda *_args: None)
    with pytest.raises(RuntimeError, match="lineage write failed"):
        importer.import_bundle(_bundle(), project_uid=project_uid, actor_uid=actor_uid)
    assert _counts(engine) == (0, 0)


def test_import_dispatches_column_effects_once_after_native_create(monkeypatch: pytest.MonkeyPatch) -> None:
    from langboard_shared.publishers import ProjectColumnPublisher
    from langboard_shared.tasks.activities import ProjectColumnActivityTask
    from langboard_shared.tasks.bots import ProjectColumnBotTask

    engine, project_uid, actor_uid = _database(monkeypatch)
    events: list[str] = []
    monkeypatch.setattr(ProjectColumnPublisher, "created", lambda *_args: events.append("publisher"))
    monkeypatch.setattr(ProjectColumnActivityTask, "project_column_created", lambda *_args: events.append("activity"))
    monkeypatch.setattr(ProjectColumnBotTask, "project_column_created", lambda *_args: events.append("bot"))

    receipt = ExternalWorkImporter().import_bundle(_bundle(), project_uid=project_uid, actor_uid=actor_uid)

    assert receipt.created == {"column": 2}
    assert _counts(engine) == (2, 2)
    assert events == ["publisher", "activity", "publisher", "activity"]


def test_native_label_create_preserves_historical_order_and_lineage(monkeypatch: pytest.MonkeyPatch) -> None:
    engine, project_uid, actor_uid = _database(monkeypatch)
    payload = _bundle().model_dump()
    payload["columns"] = []
    payload["labels"] = [{"source_id": "label-1", "name": "Imported", "color": "#112233", "order": 7}]
    bundle = ExternalWorkBundle.model_validate(payload)
    importer = ExternalWorkImporter(effect_dispatcher=lambda *_args: None)

    first = importer.import_bundle(bundle, project_uid=project_uid, actor_uid=actor_uid)
    second = importer.import_bundle(bundle, project_uid=project_uid, actor_uid=actor_uid)

    assert first.created == {"label": 1}
    assert second.unchanged == {"label": 1}
    with engine.connect() as connection:
        label = connection.execute(sa.select(ProjectLabel.__table__)).mappings().one()
        assert (label["name"], label["color"], label["order"]) == ("Imported", "#112233", 7)
