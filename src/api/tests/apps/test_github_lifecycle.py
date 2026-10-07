# ruff: noqa: F811
"""Original-byte signature and bounded lifecycle identity verification."""

import hashlib
import hmac
import json
from uuid import uuid4
import pytest
from langboard.apps.GitHubLifecycle import MAX_BODY, verify_lifecycle
from langboard.apps.GitHubManifest import GitHubManifestUnavailable
from langboard_shared.core.db import DbSession
from pydantic import SecretStr
from test_github_installation import board, installation, secrets  # noqa: F401


@pytest.fixture
def lifecycle(installation):
    service, board, connection, calls, responses = installation
    reference = service.secret_reference.create(
        board[1],
        "personal",
        "me",
        "github/signing",
        SecretStr(json.dumps({"id": 42, "webhook_secret": "test-signing-秘密"})),
    )
    with DbSession.use(readonly=False) as db:
        connection.credential_reference = reference["uri"]
        db.update(connection)
    payload = {
        "action": "removed",
        "installation": {"id": 17, "app_id": 42, "account": {"id": 7, "type": "Organization"}},
        "repositories_removed": [{"id": 99}],
        "ignored": "日本語 한국어",
    }
    return service, board, connection, payload


def signed(payload):
    body = json.dumps(payload, ensure_ascii=False).encode()
    signature = "sha256=" + hmac.new("test-signing-秘密".encode(), body, hashlib.sha256).hexdigest()
    return body, signature


def test_signature_identity_and_minimal_provenance(lifecycle):
    service, board, connection, payload = lifecycle
    body, signature = signed(payload)
    delivery = str(uuid4())
    result = verify_lifecycle(
        service, board[1], connection.get_uid(), body, signature, "installation_repositories", delivery
    )
    assert result.removed_repository_ids == (99,) and result.installation_id == 17 and result.account_id == 7
    assert result.payload_digest == hashlib.sha256(body).hexdigest() and result.delivery_id == delivery
    assert "ignored" not in repr(result) and "signing" not in repr(result)


@pytest.mark.parametrize(
    "failure",
    [
        "tamper",
        "sha1",
        "malformed",
        "oversized",
        "delivery",
        "event",
        "action",
        "app",
        "boolean",
        "duplicate",
        "overlap",
        "revoked",
    ],
)
def test_invalid_lifecycle_is_uniformly_rejected(lifecycle, failure):
    service, board, connection, payload = lifecycle
    event = "installation_repositories"
    delivery = str(uuid4())
    if failure == "action":
        payload["action"] = "deleted"
    elif failure == "app":
        payload["installation"]["app_id"] = 43
    elif failure == "boolean":
        payload["installation"]["id"] = True
    elif failure == "duplicate":
        payload["repositories_removed"].append({"id": 99})
    elif failure == "overlap":
        payload["repositories_added"] = [{"id": 99}]
    elif failure == "revoked":
        with DbSession.use(readonly=False) as db:
            connection.state = "revoked"
            db.update(connection)
    body, signature = signed(payload)
    if failure == "tamper":
        body += b" "
    elif failure == "sha1":
        signature = "sha1=" + "a" * 40
    elif failure == "malformed":
        body = b"invalid-json"
        signature = "sha256=" + hmac.new("test-signing-秘密".encode(), body, hashlib.sha256).hexdigest()
    elif failure == "oversized":
        body = b"x" * (MAX_BODY + 1)
    elif failure == "delivery":
        delivery = "invalid"
    elif failure == "event":
        event = "pull_request"
    with pytest.raises(GitHubManifestUnavailable):
        verify_lifecycle(service, board[1], connection.get_uid(), body, signature, event, delivery)


@pytest.mark.parametrize("action", ["created", "deleted", "suspend", "unsuspend", "new_permissions_accepted"])
def test_installation_actions_keep_installation_identity(lifecycle, action):
    service, board, connection, payload = lifecycle
    payload["action"] = action
    payload.pop("repositories_removed")
    body, signature = signed(payload)
    result = verify_lifecycle(service, board[1], connection.get_uid(), body, signature, "installation", str(uuid4()))
    assert result.action == action and result.installation_id == 17 and result.app_id == 42
    assert not result.added_repository_ids and not result.removed_repository_ids


def test_secret_resolution_race_rechecks_connection(lifecycle, monkeypatch):
    service, board, connection, payload = lifecycle
    original = service.secret_reference.resolve_for_runtime

    def revoke_after_resolve(*args, **kwargs):
        result = original(*args, **kwargs)
        with DbSession.use(readonly=False) as db:
            connection.state = "revoked"
            db.update(connection)
        return result

    monkeypatch.setattr(service.secret_reference, "resolve_for_runtime", revoke_after_resolve)
    body, signature = signed(payload)
    with pytest.raises(GitHubManifestUnavailable):
        verify_lifecycle(
            service, board[1], connection.get_uid(), body, signature, "installation_repositories", str(uuid4())
        )


@pytest.fixture
def receipt_storage(lifecycle, monkeypatch):
    import importlib.util
    from pathlib import Path
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    from langboard_shared.core.db.DbEngine import DbEngine

    path = Path(__file__).resolve().parents[2] / "langboard/migrations/versions/20261008093000-b541ef460d80.py"
    spec = importlib.util.spec_from_file_location("github_receipt_migration", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    engine = DbEngine.get_main_engine()
    with engine.begin() as connection:
        monkeypatch.setattr(migration, "op", Operations(MigrationContext.configure(connection)))
        migration.upgrade()
    return lifecycle, migration, engine


def test_receipt_replay_conflict_and_populated_downgrade(receipt_storage):
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    from langboard.apps.GitHubLifecycle import GitHubDeliveryConflict, receive_lifecycle
    from langboard_shared.core.db import SqlBuilder
    from langboard_shared.domain.models import GitHubLifecycleReceipt

    lifecycle, migration, engine = receipt_storage
    service, board, connection, payload = lifecycle
    body, signature = signed(payload)
    delivery = str(uuid4())
    first = receive_lifecycle(
        service, board[1], connection.get_uid(), body, signature, "installation_repositories", delivery
    )
    second = receive_lifecycle(
        service, board[1], connection.get_uid(), body, signature, "installation_repositories", delivery
    )
    assert first["receipt_uid"] == second["receipt_uid"] and not first["duplicate"] and second["duplicate"]
    payload["repositories_removed"] = [{"id": 100}]
    changed, changed_signature = signed(payload)
    with pytest.raises(GitHubDeliveryConflict):
        receive_lifecycle(
            service, board[1], connection.get_uid(), changed, changed_signature, "installation_repositories", delivery
        )
    with DbSession.use(readonly=False) as db:
        rows = db.exec(SqlBuilder.select.table(GitHubLifecycleReceipt)).all()
        assert len(rows) == 1 and rows[0].removed_repository_ids == [99]
        assert rows[0].payload_digest == hashlib.sha256(body).hexdigest()
        assert "ignored" not in rows[0].model_dump() and "webhook_secret" not in rows[0].model_dump()
    with engine.begin() as db:
        migration.op = Operations(MigrationContext.configure(db))
        with pytest.raises(RuntimeError, match="Cannot discard"):
            migration.downgrade()


def test_invalid_signature_never_creates_receipt(receipt_storage):
    from langboard.apps.GitHubLifecycle import receive_lifecycle
    from langboard_shared.core.db import SqlBuilder
    from langboard_shared.domain.models import GitHubLifecycleReceipt

    lifecycle, migration, engine = receipt_storage
    service, board, connection, payload = lifecycle
    body, signature = signed(payload)
    with pytest.raises(GitHubManifestUnavailable):
        receive_lifecycle(
            service, board[1], connection.get_uid(), body + b" ", signature, "installation_repositories", str(uuid4())
        )
    with DbSession.use(readonly=False) as db:
        assert not db.exec(SqlBuilder.select.table(GitHubLifecycleReceipt)).all()
    from alembic.migration import MigrationContext
    from alembic.operations import Operations

    with engine.begin() as db:
        migration.op = Operations(MigrationContext.configure(db))
        migration.downgrade()
        migration.upgrade()


def test_receipt_rechecks_connection_after_verification(receipt_storage, monkeypatch):
    from langboard.apps import GitHubLifecycle as github
    from langboard_shared.core.db import SqlBuilder
    from langboard_shared.domain.models import GitHubLifecycleReceipt

    lifecycle, migration, engine = receipt_storage
    service, board, connection, payload = lifecycle
    body, signature = signed(payload)
    verify = github.verify_lifecycle

    def revoke(*args):
        verified = verify(*args)
        with DbSession.use(readonly=False) as db:
            connection.state = "revoked"
            db.update(connection)
        return verified

    monkeypatch.setattr(github, "verify_lifecycle", revoke)
    with pytest.raises(GitHubManifestUnavailable):
        github.receive_lifecycle(
            service, board[1], connection.get_uid(), body, signature, "installation_repositories", str(uuid4())
        )
    with DbSession.use(readonly=False) as db:
        assert not db.exec(SqlBuilder.select.table(GitHubLifecycleReceipt)).all()


def test_concurrent_postgres_delivery_reuses_receipt(receipt_storage, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    from langboard.apps import GitHubLifecycle as github

    lifecycle, migration, engine = receipt_storage
    if engine.dialect.name != "postgresql":
        pytest.skip("PostgreSQL row lock concurrency check")
    service, board, connection, payload = lifecycle
    body, signature = signed(payload)
    delivery = str(uuid4())
    verified = github.verify_lifecycle(
        service, board[1], connection.get_uid(), body, signature, "installation_repositories", delivery
    )
    barrier = Barrier(2)

    def synchronize(*args):
        barrier.wait(timeout=10)
        return verified

    monkeypatch.setattr(github, "verify_lifecycle", synchronize)

    def receive():
        return github.receive_lifecycle(
            service, board[1], connection.get_uid(), body, signature, "installation_repositories", delivery
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: receive(), range(2)))
    assert results[0]["receipt_uid"] == results[1]["receipt_uid"]
    assert sorted(result["duplicate"] for result in results) == [False, True]
