import os
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
import pytest
from sqlalchemy import create_engine, text


os.environ.setdefault("PROJECT_NAME", "langboard")

from langboard_shared.core.db.DbEngine import DbEngine  # noqa: E402
from langboard_shared.core.types import SnowflakeID  # noqa: E402
from langboard_shared.domain.models import Project, User  # noqa: E402
from langboard_shared.infrastructure.repositories.factory.ProjectAssignedUserRepository import (  # noqa: E402
    ProjectAssignedUserRepository,
)


DATABASE_URL = os.getenv("LANGBOARD_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not DATABASE_URL, reason="requires LANGBOARD_TEST_DATABASE_URL")


def _create_tables(engine) -> None:
    with engine.begin() as connection:
        for table in (
            "project_user_relationship",
            "project_role",
            "user_identity_link",
            "project_assigned_user",
            "project",
        ):
            connection.execute(text(f"DROP TABLE IF EXISTS {table}"))
        connection.execute(
            text("CREATE TABLE project (id BIGINT PRIMARY KEY, owner_id BIGINT NOT NULL, deleted_at TIMESTAMP)")
        )
        connection.execute(
            text(
                """
                CREATE TABLE project_assigned_user (
                    id BIGINT PRIMARY KEY,
                    created_at TIMESTAMP NOT NULL,
                    updated_at TIMESTAMP NOT NULL,
                    project_id BIGINT NOT NULL,
                    user_id BIGINT NOT NULL,
                    starred BOOLEAN NOT NULL,
                    last_viewed_at TIMESTAMP NOT NULL
                )
                """
            )
        )
        connection.execute(
            text(
                """
                CREATE TABLE user_identity_link (
                    id BIGINT PRIMARY KEY,
                    user_id BIGINT NOT NULL,
                    provider VARCHAR NOT NULL,
                    issuer VARCHAR NOT NULL
                )
                """
            )
        )
        connection.execute(
            text(
                """
                CREATE TABLE project_role (
                    id BIGINT PRIMARY KEY,
                    created_at TIMESTAMP NOT NULL,
                    updated_at TIMESTAMP NOT NULL,
                    actions TEXT NOT NULL,
                    user_id BIGINT NOT NULL,
                    project_id BIGINT NOT NULL
                )
                """
            )
        )
        connection.execute(
            text(
                """
                CREATE TABLE project_user_relationship (
                    id BIGINT PRIMARY KEY,
                    created_at TIMESTAMP NOT NULL,
                    updated_at TIMESTAMP NOT NULL,
                    project_id BIGINT NOT NULL,
                    user_id BIGINT NOT NULL,
                    related_user_id BIGINT NOT NULL,
                    last_related_at TIMESTAMP NOT NULL,
                    UNIQUE (project_id, user_id, related_user_id)
                )
                """
            )
        )
        connection.execute(text("INSERT INTO project (id, owner_id) VALUES (1, 10)"))


def _drop_tables(engine) -> None:
    with engine.begin() as connection:
        for table in (
            "project_user_relationship",
            "project_role",
            "user_identity_link",
            "project_assigned_user",
            "project",
        ):
            connection.execute(text(f"DROP TABLE IF EXISTS {table}"))


def test_concurrent_member_ensure_creates_one_assignment(monkeypatch: pytest.MonkeyPatch) -> None:
    """Project locking makes the read-then-insert path idempotent under real concurrency."""

    assert DATABASE_URL is not None
    engine = create_engine(DATABASE_URL)
    _create_tables(engine)
    monkeypatch.setattr(DbEngine, "get_main_engine", lambda: engine)
    repository = ProjectAssignedUserRepository(lambda _type: None, lambda _name: None)
    project = Project.model_construct(id=SnowflakeID(1))
    user = User.model_construct(id=SnowflakeID(20))
    start = Barrier(2)

    def ensure() -> bool:
        start.wait()
        return repository.ensure_assigned(project, user)[1]

    try:
        with ThreadPoolExecutor(max_workers=2) as executor:
            created = [result.result(timeout=10) for result in (executor.submit(ensure), executor.submit(ensure))]
        assert sorted(created) == [False, True]
        with engine.connect() as connection:
            count = connection.execute(text("SELECT count(*) FROM project_assigned_user")).scalar_one()
        assert count == 1
    finally:
        _drop_tables(engine)
        engine.dispose()


def test_entitlement_verification_failure_rolls_back_the_whole_uow(monkeypatch: pytest.MonkeyPatch) -> None:
    """Assignment, role, and relationship writes disappear together when verification fails."""

    assert DATABASE_URL is not None
    engine = create_engine(DATABASE_URL)
    _create_tables(engine)
    monkeypatch.setattr(DbEngine, "get_main_engine", lambda: engine)
    repository = ProjectAssignedUserRepository(lambda _type: None, lambda _name: None)
    project = Project.model_construct(id=SnowflakeID(1))
    owner = User.model_construct(id=SnowflakeID(10))
    employee = User.model_construct(id=SnowflakeID(20))
    repository.ensure_assigned(project, owner)
    monkeypatch.setattr(
        repository,
        "_verify_scim_project_roles",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(ValueError("injected verification failure")),
    )

    try:
        with pytest.raises(ValueError, match="injected verification failure"):
            repository.reconcile_scim_project_roles(
                project,
                "https://directory.example/scim",
                {employee.id: (employee, ["read", "card_write"])},
            )
        with engine.connect() as connection:
            assignments = (
                connection.execute(text("SELECT user_id FROM project_assigned_user ORDER BY user_id")).scalars().all()
            )
            role_count = connection.execute(text("SELECT count(*) FROM project_role")).scalar_one()
            relationship_count = connection.execute(text("SELECT count(*) FROM project_user_relationship")).scalar_one()
        assert assignments == [owner.id]
        assert role_count == 0
        assert relationship_count == 0
    finally:
        _drop_tables(engine)
        engine.dispose()
