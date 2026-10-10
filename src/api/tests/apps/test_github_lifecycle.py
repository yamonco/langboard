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
        # Board fixture uses current ORM; reconstruct the preceding deployed schema.
        with migration.op.batch_alter_table("app_resource_binding") as batch:
            batch.drop_column("access_revision")
    spec = importlib.util.spec_from_file_location(
        "github_invalidation_migration", path.with_name("20261008095000-c652f0571e91.py")
    )
    invalidation = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(invalidation)
    with engine.begin() as connection:
        invalidation.op = Operations(MigrationContext.configure(connection))
        invalidation.upgrade()
    spec = importlib.util.spec_from_file_location(
        "github_health_migration", path.with_name("20261008103000-d76301682fa2.py")
    )
    health = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(health)
    with engine.begin() as connection:
        health.op = Operations(MigrationContext.configure(connection))
        health.upgrade()
    from langboard.apps import GitHubHealthWorker

    monkeypatch.setattr(GitHubHealthWorker, "enqueue", lambda uid: None)
    from langboard_shared.publishers import CardPublisher

    monkeypatch.setattr(CardPublisher, "put_dispather", lambda *args: None)
    migration.health = health
    migration.invalidation = invalidation
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
        migration.health.op = Operations(MigrationContext.configure(db))
        migration.health.downgrade()
        migration.downgrade()
        migration.upgrade()
        migration.health.upgrade()


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


@pytest.mark.parametrize("board", ["sqlite-http"], indirect=True)
def test_native_webhook_receipt_without_browser_identity(receipt_storage, monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from langboard.routes.board.BoardGitHubAppApi import receive_github_lifecycle
    from langboard_shared.core.db import SqlBuilder
    from langboard_shared.core.routing import AppRouter
    from langboard_shared.domain.models import GitHubLifecycleReceipt

    lifecycle, migration, engine = receipt_storage
    service, board, connection, payload = lifecycle
    import importlib
    from langboard.middlewares.ApiAuthMiddleware import ApiAuthMiddleware

    service.close = lambda: None
    monkeypatch.setattr(
        importlib.import_module("langboard.middlewares.ApiAuthMiddleware"), "DomainService", lambda: service
    )
    app = FastAPI()
    app.include_router(AppRouter.api)
    app.add_middleware(ApiAuthMiddleware, routes=AppRouter.api.routes)
    for route in app.routes:
        if getattr(route, "endpoint", None) is receive_github_lifecycle:
            for dependency in route.dependant.dependencies:
                if dependency.name == "service":
                    app.dependency_overrides[dependency.call] = lambda: service
    body, signature = signed(payload)
    headers = {
        "Content-Type": "application/json",
        "X-Hub-Signature-256": signature,
        "X-GitHub-Event": "installation_repositories",
        "X-GitHub-Delivery": str(uuid4()),
    }
    with TestClient(app) as client:
        first = client.post("/apps/github/events", content=body, headers=headers)
        assert first.status_code == 202, first.text
        assert client.post("/apps/github/events", content=body, headers=headers).status_code == 202
        ping_body, ping_signature = signed({"zen": "ignored", "hook_id": 123, "hook": {"id": 123}})
        ping_headers = {
            **headers,
            "X-GitHub-Event": "ping",
            "X-GitHub-Delivery": str(uuid4()),
            "X-Hub-Signature-256": ping_signature,
            "X-GitHub-Hook-Installation-Target-ID": "42",
        }
        assert client.post("/apps/github/events", content=ping_body, headers=ping_headers).status_code == 202
        assert (
            client.post(
                "/apps/github/events",
                content=ping_body,
                headers={**ping_headers, "X-GitHub-Hook-Installation-Target-ID": "43"},
            ).status_code
            == 400
        )
        payload["repositories_removed"] = [{"id": 100}]
        changed, changed_signature = signed(payload)
        assert (
            client.post(
                "/apps/github/events", content=changed, headers={**headers, "X-Hub-Signature-256": changed_signature}
            ).status_code
            == 409
        )
        assert client.post("/apps/github/events", content=body + b" ", headers=headers).status_code == 400
        assert (
            client.post(
                "/apps/github/events", content=body, headers={**headers, "Content-Type": "text/plain"}
            ).status_code
            == 415
        )
        assert (
            client.post(
                "/apps/github/events", content=body, headers={**headers, "Content-Encoding": "gzip"}
            ).status_code
            == 415
        )
        assert client.post("/apps/github/events", content=b"x" * (MAX_BODY + 1), headers=headers).status_code == 413
        assert (
            client.post("/apps/github/events", content=body, headers={**headers, "Content-Length": "0"}).status_code
            == 400
        )
        assert client.post("/apps/github/events", content=iter([body]), headers=headers).status_code == 202
        assert (
            client.post("/apps/github/events", content=iter([b"x" * MAX_BODY, b"x"]), headers=headers).status_code
            == 413
        )
        duplicated = list(headers.items()) + [("X-GitHub-Event", "installation")]
        assert client.post("/apps/github/events", content=body, headers=duplicated).status_code == 400
    with DbSession.use(readonly=False) as db:
        assert len(db.exec(SqlBuilder.select.table(GitHubLifecycleReceipt)).all()) == 2


@pytest.mark.parametrize("failure", ["unknown", "ambiguous", "inactive_owner", "forged_app"])
def test_external_routing_does_not_trust_sender_or_candidate(receipt_storage, failure):
    from langboard.apps.GitHubLifecycle import receive_external_lifecycle
    from langboard_shared.core.db import SqlBuilder
    from langboard_shared.domain.models import AppConnection, GitHubLifecycleReceipt

    lifecycle, migration, engine = receipt_storage
    service, board, connection, payload = lifecycle
    payload["sender"] = {"id": int(board[1].id), "is_admin": True}
    if failure == "unknown":
        payload["installation"]["app_id"] = 43
    elif failure == "ambiguous":
        with DbSession.use(readonly=False) as db:
            db.insert(AppConnection(app_key="github", owner_id=board[1].id, external_account_id="42"))
    elif failure == "inactive_owner":
        with DbSession.use(readonly=False) as db:
            board[1].activated_at = None
            db.update(board[1])
    body, signature = signed(payload)
    if failure == "forged_app":
        signature = "sha256=" + "0" * 64
    with pytest.raises(GitHubManifestUnavailable):
        receive_external_lifecycle(service, body, signature, "installation_repositories", str(uuid4()))
    with DbSession.use(readonly=False) as db:
        assert not db.exec(SqlBuilder.select.table(GitHubLifecycleReceipt)).all()


@pytest.mark.parametrize(
    "action", ["deleted", "suspend", "unsuspend", "created", "new_permissions_accepted", "removed", "added"]
)
def test_lifecycle_invalidates_only_matching_selected_resources(receipt_storage, action, monkeypatch):
    from langboard_shared.helpers import InfraHelper
    from langboard_shared.publishers import CardPublisher

    notices = []
    monkeypatch.setattr(CardPublisher, "app_signal_changed", notices.append)
    from langboard.apps.GitHubLifecycle import receive_lifecycle
    from langboard.apps.GitHubResources import resource_snapshot
    from langboard_shared.core.db import SqlBuilder
    from langboard_shared.domain.models import AppResourceBinding, BoardAppBinding, GitHubLifecycleReceipt, Project

    lifecycle, migration, engine = receipt_storage
    service, board, connection, payload = lifecycle
    with DbSession.use(readonly=False) as db:
        unrelated = Project(owner_id=board[1].id, title="Unrelated installation fixture")
        db.insert(unrelated)
        bindings = []
        for project_id in (10, 11, unrelated.id):
            binding = BoardAppBinding(project_id=project_id, app_key="github")
            db.insert(binding)
            bindings.append(binding)
        resources = []
        for index, (binding, installation_id, account_id, selected, repo) in enumerate(
            [
                (bindings[0], 17, 7, True, 99),
                (bindings[1], 17, 7, True, 99),
                (bindings[2], 18, 7, True, 100),
                (bindings[0], 17, 8, True, 101),
                (bindings[0], 17, 7, False, 102),
                (bindings[0], 17, 7, True, 103),
            ]
        ):
            row = AppResourceBinding(
                board_binding_id=binding.id,
                connection_id=connection.id,
                resource_type="repository",
                external_resource_id=str(repo),
                is_selected=selected,
                access_state="granted",
                health="healthy",
                resource_path=[
                    {"type": "installation", "id": str(installation_id)},
                    {"type": "account", "id": str(account_id)},
                ],
            )
            db.insert(row)
            resources.append(row)
        before = resource_snapshot(db, bindings[0])["revision"]
    payload["action"] = action
    payload.pop("repositories_removed")
    event = "installation"
    if action in {"removed", "added"}:
        event = "installation_repositories"
        payload["repositories_" + action] = [{"id": 99}]
    body, signature = signed(payload)
    delivery = str(uuid4())
    with pytest.raises(RuntimeError, match="notification rollback"):
        with DbSession.atomic():
            receive_lifecycle(service, board[1], connection.get_uid(), body, signature, event, delivery)
            assert not notices
            raise RuntimeError("notification rollback")
    assert not notices
    first = receive_lifecycle(service, board[1], connection.get_uid(), body, signature, event, delivery)
    assert sorted(notices) == sorted(InfraHelper.convert_uid(value) for value in (10, 11))
    # Replay does not invalidate again, even after an explicit API refresh restored health.
    with DbSession.use(readonly=False) as db:
        rows = {row.get_uid(): row for row in db.exec(SqlBuilder.select.table(AppResourceBinding)).all()}
        expected = {0, 1} if event == "installation_repositories" else {0, 1, 5}
        for index, original in enumerate(resources):
            row = rows[original.get_uid()]
            assert row.access_revision == (1 if index in expected else 0)
            assert row.health == ("unavailable" if index in expected else "healthy")
            assert row.is_selected == original.is_selected
        after = resource_snapshot(db, bindings[0])["revision"]
        assert after != before
        row = rows[resources[0].get_uid()]
        row.access_state, row.health = "granted", "healthy"
        db.update(row)
        receipt = db.exec(SqlBuilder.select.table(GitHubLifecycleReceipt)).first()
        assert receipt.invalidated
    duplicate = receive_lifecycle(service, board[1], connection.get_uid(), body, signature, event, delivery)
    assert duplicate["duplicate"] and duplicate["receipt_uid"] == first["receipt_uid"]
    assert len(notices) == 2
    with DbSession.use(readonly=False) as db:
        row = db.exec(
            SqlBuilder.select.table(AppResourceBinding).where(AppResourceBinding.id == resources[0].id)
        ).first()
        assert row.health == "healthy" and row.access_revision == 1
    # A different delayed event still cannot grant access; revision changes despite already-invalid state.
    receive_lifecycle(service, board[1], connection.get_uid(), body, signature, event, str(uuid4()))
    with DbSession.use(readonly=False) as db:
        assert resource_snapshot(db, bindings[0])["revision"] != after
    from alembic.migration import MigrationContext
    from alembic.operations import Operations

    with engine.begin() as db:
        migration.invalidation.op = Operations(MigrationContext.configure(db))
        with pytest.raises(RuntimeError, match="Cannot discard"):
            migration.invalidation.downgrade()


def test_receipt_and_invalidation_roll_back_together(receipt_storage, monkeypatch):
    from langboard.apps import GitHubLifecycle as github
    from langboard_shared.core.db import SqlBuilder
    from langboard_shared.domain.models import GitHubLifecycleReceipt

    lifecycle, migration, engine = receipt_storage
    service, board, connection, payload = lifecycle
    body, signature = signed(payload)

    def fail(db, receipt):
        raise RuntimeError("fixture resource update failure")

    monkeypatch.setattr(github, "_invalidate_resources", fail)
    with pytest.raises(RuntimeError, match="fixture resource"):
        github.receive_lifecycle(
            service, board[1], connection.get_uid(), body, signature, "installation_repositories", str(uuid4())
        )
    with DbSession.use(readonly=False) as db:
        assert not db.exec(SqlBuilder.select.table(GitHubLifecycleReceipt)).all()


def test_empty_invalidation_migration_roundtrip(receipt_storage):
    from alembic.migration import MigrationContext
    from alembic.operations import Operations

    lifecycle, migration, engine = receipt_storage
    with engine.begin() as db:
        migration.invalidation.op = Operations(MigrationContext.configure(db))
        migration.invalidation.downgrade()
        migration.invalidation.upgrade()


def test_refresh_cannot_commit_after_repeated_unknown_invalidation(receipt_storage, monkeypatch):
    from langboard.apps import GitHubResources as resources
    from langboard.apps.GitHubLifecycle import receive_lifecycle
    from langboard_shared.core.db import SqlBuilder
    from langboard_shared.domain.models import AppResourceBinding, BoardAppBinding

    lifecycle, migration, engine = receipt_storage
    service, board, connection, payload = lifecycle
    with DbSession.use(readonly=False) as db:
        binding = BoardAppBinding(project_id=board[2].id, app_key="github")
        db.insert(binding)
        row = AppResourceBinding(
            board_binding_id=binding.id,
            connection_id=connection.id,
            resource_type="repository",
            external_resource_id="99",
            access_state="unknown",
            health="unavailable",
            resource_path=[{"type": "installation", "id": "17"}, {"type": "account", "id": "7"}],
        )
        db.insert(row)
    before = resources.get_resources(service, board[1], board[2].get_uid())
    body, signature = signed(payload)

    def stale_inspection(*args, **kwargs):
        # The external query began before another lifecycle invalidated already-unknown evidence.
        receive_lifecycle(
            service, board[1], connection.get_uid(), body, signature, "installation_repositories", str(uuid4())
        )
        return {"repositories": [{"id": 99, "archived": False}]}

    monkeypatch.setattr(resources, "inspect_installation", stale_inspection)
    with pytest.raises(resources.GitHubResourceConflict):
        resources.refresh_resources(service, board[1], board[2].get_uid(), connection.get_uid(), before["revision"])
    after = resources.get_resources(service, board[1], board[2].get_uid())
    assert after["revision"] != before["revision"] and after["items"][0]["access_revision"] == 1
    with DbSession.use(readonly=False) as db:
        current = db.exec(SqlBuilder.select.table(AppResourceBinding).where(AppResourceBinding.id == row.id)).first()
        assert current.health == "unavailable" and current.access_state == "unknown"


@pytest.mark.parametrize("failure", [None, "tamper", "target", "hook", "boolean", "installation", "action"])
def test_signed_ping_is_receipt_only_without_installation(receipt_storage, failure):
    from langboard.apps.GitHubLifecycle import receive_external_lifecycle
    from langboard_shared.core.db import SqlBuilder
    from langboard_shared.domain.models import AppResourceBinding, BoardAppBinding, GitHubLifecycleReceipt

    lifecycle, migration, engine = receipt_storage
    service, board, connection, payload = lifecycle
    with DbSession.use(readonly=False) as db:
        binding = BoardAppBinding(project_id=board[2].id, app_key="github")
        db.insert(binding)
        row = AppResourceBinding(
            board_binding_id=binding.id,
            connection_id=connection.id,
            resource_type="repository",
            external_resource_id="99",
            access_state="granted",
            health="healthy",
            resource_path=[{"type": "installation", "id": "17"}, {"type": "account", "id": "7"}],
        )
        db.insert(row)
    ping = {"zen": "must not be stored", "hook_id": 123, "hook": {"id": 123}}
    target = "42"
    if failure == "hook":
        ping["hook"]["id"] = 124
    elif failure == "boolean":
        ping["hook_id"] = True
    elif failure == "installation":
        ping["installation"] = payload["installation"]
    elif failure == "action":
        ping["action"] = "deleted"
    elif failure == "target":
        target = "43"
    body, signature = signed(ping)
    if failure == "tamper":
        body += b" "
    delivery = str(uuid4())
    if failure:
        with pytest.raises(GitHubManifestUnavailable):
            receive_external_lifecycle(service, body, signature, "ping", delivery, target)
    else:
        first = receive_external_lifecycle(service, body, signature, "ping", delivery, target)
        duplicate = receive_external_lifecycle(service, body, signature, "ping", delivery, target)
        assert first["receipt_uid"] == duplicate["receipt_uid"] and duplicate["duplicate"]
    with DbSession.use(readonly=False) as db:
        current = db.exec(SqlBuilder.select.table(AppResourceBinding).where(AppResourceBinding.id == row.id)).first()
        assert current.access_revision == 0 and current.access_state == "granted" and current.health == "healthy"
        receipts = db.exec(SqlBuilder.select.table(GitHubLifecycleReceipt)).all()
        assert len(receipts) == (0 if failure else 1)
        if receipts:
            assert receipts[0].installation_id == "" and receipts[0].account_id == ""
            assert receipts[0].event == "ping" and receipts[0].invalidated and receipts[0].added_repository_ids == []
            assert "zen" not in receipts[0].model_dump()


@pytest.fixture
def private_receipt_storage(receipt_storage):
    # Automatic refresh is authorized only for this connected owner's private board.
    lifecycle, *_ = receipt_storage
    _, board, connection, _ = lifecycle
    with DbSession.atomic() as db:
        connection.state = "connected"
        board[2].owner_id = board[1].id
        db.update(connection)
        db.update(board[2])
    return receipt_storage


@pytest.mark.parametrize("failure", [None, "permission", "ping", "owner_inactive", "connection_changed", "shared", "shared_during_query"])
def test_receipt_refresh_revalidates_authority_and_scopes_installation(private_receipt_storage, monkeypatch, failure):
    from langboard.apps import GitHubResources as resources
    from langboard.apps.GitHubHealth import refresh_receipt_resources
    from langboard.apps.GitHubLifecycle import receive_lifecycle
    from langboard_shared.core.db import SqlBuilder
    from langboard_shared.domain.models import AppResourceBinding, BoardAppBinding

    lifecycle, migration, engine = private_receipt_storage
    service, board, connection, payload = lifecycle
    with DbSession.use(readonly=False) as db:
        binding = BoardAppBinding(project_id=board[2].id, app_key="github")
        db.insert(binding)
        rows = []
        for installation_id in (17, 18):
            row = AppResourceBinding(
                board_binding_id=binding.id,
                connection_id=connection.id,
                resource_type="repository",
                external_resource_id=str(installation_id),
                access_state="unknown",
                health="unavailable",
                resource_path=[{"type": "installation", "id": str(installation_id)}, {"type": "account", "id": "7"}],
            )
            db.insert(row)
            rows.append(row)
    if failure == "ping":
        payload = {"hook_id": 123}
    else:
        payload = {"action": "unsuspend", "installation": payload["installation"]}
    body, signature = signed(payload)
    event = "ping" if failure == "ping" else "installation"
    receipt = receive_lifecycle(service, board[1], connection.get_uid(), body, signature, event, str(uuid4()))
    with DbSession.use(readonly=False) as db:
        if failure == "permission":
            board[4].actions = ["read"]
            board[2].owner_id = 2
            db.update(board[4])
            db.update(board[2])
        elif failure == "connection_changed":
            connection.external_account_id = "43"
            db.update(connection)
        elif failure == "owner_inactive":
            board[1].activated_at = None
            db.update(board[1])
        elif failure == "shared":
            from langboard_shared.domain.models import ProjectAssignedUser
            db.insert(ProjectAssignedUser(project_id=board[2].id, user_id=2))
    calls = []

    def inspect(*args, **kwargs):
        calls.append((args, kwargs))
        assert args[4] == 17 and kwargs["repository_ids"] == (17,)
        if failure == "shared_during_query":
            from langboard_shared.domain.models import ProjectAssignedUser
            with DbSession.atomic() as db:
                db.insert(ProjectAssignedUser(project_id=board[2].id, user_id=2))
        return {"repositories": [{"id": 17, "archived": False}]}

    monkeypatch.setattr(resources, "inspect_installation", inspect)
    if failure:
        with pytest.raises(GitHubManifestUnavailable):
            refresh_receipt_resources(service, receipt["receipt_uid"], board[2].get_uid())
        assert len(calls) == (1 if failure == "shared_during_query" else 0)
        with DbSession.use(readonly=False) as db:
            current = db.exec(SqlBuilder.select.table(AppResourceBinding).where(AppResourceBinding.id == rows[0].id)).first()
            assert current.access_state == "unknown" and current.health == "unavailable"
    else:
        result = refresh_receipt_resources(service, receipt["receipt_uid"], board[2].get_uid())
        assert result["refreshed_count"] == 1 and len(calls) == 1
        with DbSession.use(readonly=False) as db:
            own = db.exec(
                SqlBuilder.select.table(AppResourceBinding).where(AppResourceBinding.id == rows[0].id)
            ).first()
            other = db.exec(
                SqlBuilder.select.table(AppResourceBinding).where(AppResourceBinding.id == rows[1].id)
            ).first()
            assert own.health == "healthy" and other.health == "unavailable"


def test_receipt_refresh_is_limited_to_25_resource_pages(private_receipt_storage, monkeypatch):
    from langboard_shared.publishers import CardPublisher

    notices = []
    monkeypatch.setattr(CardPublisher, "app_signal_changed", notices.append)
    from langboard.apps import GitHubResources as resources
    from langboard.apps.GitHubHealth import refresh_receipt_resources
    from langboard.apps.GitHubLifecycle import receive_lifecycle
    from langboard_shared.domain.models import AppResourceBinding, BoardAppBinding
    from sqlalchemy import insert

    lifecycle, migration, engine = private_receipt_storage
    service, board, connection, payload = lifecycle
    with DbSession.use(readonly=False) as db:
        binding = BoardAppBinding(project_id=board[2].id, app_key="github")
        db.insert(binding)
        for i in range(40):
            row = AppResourceBinding(
                id=100 + i,
                board_binding_id=binding.id,
                connection_id=connection.id,
                resource_type="repository",
                external_resource_id=str(100 + i),
                resource_path=[{"type": "installation", "id": "17"}, {"type": "account", "id": "7"}],
            )
            db.exec(insert(AppResourceBinding).values({column.name: getattr(row, column.name) for column in row.__table__.columns}))
        for i in range(100):
            db.insert(
                AppResourceBinding(
                    board_binding_id=binding.id,
                    connection_id=connection.id,
                    resource_type="repository",
                    external_resource_id=str(1000 + i),
                    resource_path=[{"type": "installation", "id": "18"}, {"type": "account", "id": "7"}],
                )
            )
    body, signature = signed({"action": "created", "installation": payload["installation"]})
    receipt = receive_lifecycle(service, board[1], connection.get_uid(), body, signature, "installation", str(uuid4()))
    assert notices == [board[2].get_uid()]
    notices.clear()
    sizes = []
    visited = []

    def inspect(*args, **kwargs):
        ids = kwargs["repository_ids"]
        sizes.append(len(ids))
        visited.extend(ids)
        return {"repositories": [{"id": uid, "archived": False} for uid in ids]}

    monkeypatch.setattr(resources, "inspect_installation", inspect)
    monkeypatch.setattr(
        resources, "resource_snapshot", lambda *args: pytest.fail("Receipt refresh must not load every board resource")
    )
    from sqlalchemy import event

    selects = []

    def capture(_connection, _cursor, statement, _parameters, _context, _many):
        if statement.lstrip().upper().startswith("SELECT") and "FROM app_resource_binding" in statement:
            selects.append(statement)

    event.listen(engine, "before_cursor_execute", capture)
    try:
        first = refresh_receipt_resources(service, receipt["receipt_uid"], board[2].get_uid())
        assert first["refreshed_count"] == 25 and first["next_cursor"]
        assert notices == [board[2].get_uid()]
        second = refresh_receipt_resources(service, receipt["receipt_uid"], board[2].get_uid(), first["next_cursor"])
        assert notices == [board[2].get_uid()] * 2
        assert second["refreshed_count"] == 15 and second["next_cursor"] is None and sizes == [25, 15]
        assert visited == list(range(100, 140))
        assert selects and all(
            "LIMIT" in statement.upper() or "WHERE app_resource_binding.id =" in statement for statement in selects
        )
    finally:
        event.remove(engine, "before_cursor_execute", capture)


@pytest.mark.parametrize("change", ["selection", "access_revision", "unrelated"])
def test_receipt_page_rechecks_scoped_changes_after_api(private_receipt_storage, monkeypatch, change):
    from langboard.apps import GitHubResources as resources
    from langboard.apps.GitHubHealth import refresh_receipt_resources
    from langboard.apps.GitHubLifecycle import receive_lifecycle
    from langboard.apps.GitHubResources import GitHubResourceConflict
    from langboard_shared.core.db import SqlBuilder
    from langboard_shared.domain.models import AppResourceBinding, BoardAppBinding

    lifecycle, _migration, _engine = private_receipt_storage
    service, board, connection, payload = lifecycle
    with DbSession.use(readonly=False) as db:
        binding = BoardAppBinding(project_id=board[2].id, app_key="github")
        db.insert(binding)
        rows = []
        for uid, installation in [(99, 17), (100, 17), (101, 18)]:
            row = AppResourceBinding(
                board_binding_id=binding.id, connection_id=connection.id,
                resource_type="repository", external_resource_id=str(uid),
                resource_path=[{"type": "installation", "id": str(installation)}, {"type": "account", "id": "7"}],
            )
            db.insert(row)
            rows.append(row)
    body, signature = signed({"action": "created", "installation": payload["installation"]})
    receipt = receive_lifecycle(service, board[1], connection.get_uid(), body, signature, "installation", str(uuid4()))

    def inspect(*args, **kwargs):
        assert kwargs["repository_ids"] == (99, 100)
        with DbSession.use(readonly=False) as db:
            row = rows[2] if change == "unrelated" else rows[0]
            if change == "selection":
                row.is_selected = False
            else:
                row.access_revision += 1
            db.update(row)
        return {"repositories": [{"id": uid, "archived": False} for uid in (99, 100)]}

    monkeypatch.setattr(resources, "inspect_installation", inspect)
    if change == "unrelated":
        assert refresh_receipt_resources(service, receipt["receipt_uid"], board[2].get_uid())["refreshed_count"] == 2
    else:
        with pytest.raises(GitHubResourceConflict):
            refresh_receipt_resources(service, receipt["receipt_uid"], board[2].get_uid())
    with DbSession.use(readonly=False) as db:
        stored = db.exec(SqlBuilder.select.table(AppResourceBinding).where(AppResourceBinding.id == rows[0].id)).first()
        assert stored.health == ("healthy" if change == "unrelated" else "unknown")
        assert stored.is_selected == (change != "selection")


def test_receipt_refresh_fences_connection_changed_between_receipt_and_query(receipt_storage, monkeypatch):
    from langboard.apps import GitHubHealth as health
    from langboard.apps.GitHubLifecycle import receive_lifecycle
    from langboard.apps.GitHubResources import GitHubResourceConflict
    from langboard_shared.domain.models import BoardAppBinding

    lifecycle, migration, engine = receipt_storage
    service, board, connection, payload = lifecycle
    with DbSession.use(readonly=False) as db:
        db.insert(BoardAppBinding(project_id=board[2].id, app_key="github"))
    body, signature = signed(payload)
    receipt = receive_lifecycle(
        service, board[1], connection.get_uid(), body, signature, "installation_repositories", str(uuid4())
    )
    refresh = health.refresh_resources

    def change(*args, **kwargs):
        with DbSession.use(readonly=False) as db:
            connection.external_account_id = "43"
            db.update(connection)
        return refresh(*args, **kwargs)

    monkeypatch.setattr(health, "refresh_resources", change)
    with pytest.raises(GitHubResourceConflict):
        health.refresh_receipt_resources(service, receipt["receipt_uid"], board[2].get_uid())


@pytest.fixture
def health_job(private_receipt_storage, monkeypatch):
    from langboard.apps import GitHubHealthWorker as worker
    from langboard.apps.GitHubLifecycle import receive_lifecycle
    from langboard_shared.core.db import SqlBuilder
    from langboard_shared.domain.models import AppResourceBinding, BoardAppBinding, GitHubHealthJob

    lifecycle, migration, engine = private_receipt_storage
    service, board, connection, payload = lifecycle
    dispatched = []
    monkeypatch.setattr(worker, "enqueue", dispatched.append)
    with DbSession.use(readonly=False) as db:
        for project_id, installation_id, count in ((10, 17, 40), (11, 17, 1)):
            binding = BoardAppBinding(project_id=project_id, app_key="github")
            db.insert(binding)
            for i in range(count):
                db.insert(
                    AppResourceBinding(
                        board_binding_id=binding.id,
                        connection_id=connection.id,
                        resource_type="repository",
                        external_resource_id=str(100 + i),
                        resource_path=[
                            {"type": "installation", "id": str(installation_id)},
                            {"type": "account", "id": "7"},
                        ],
                    )
                )
    payload = {"action": "unsuspend", "installation": payload["installation"]}
    body, signature = signed(payload)
    delivery = str(uuid4())

    def receive():
        return receive_lifecycle(service, board[1], connection.get_uid(), body, signature, "installation", delivery)

    receive()
    with DbSession.use(readonly=False) as db:
        job = db.exec(SqlBuilder.select.table(GitHubHealthJob)).first()
    return worker, service, board, connection, job, dispatched, receive, migration, engine


@pytest.mark.parametrize("suspension", [None, "before_query", "during_query"])
def test_organization_health_worker_rechecks_live_scope(private_receipt_storage, monkeypatch, suspension):
    from langboard.apps import GitHubHealthWorker as worker
    from langboard.apps import GitHubResources as resources
    from langboard.apps.GitHubLifecycle import receive_lifecycle
    from langboard_shared.core.db import SqlBuilder
    from langboard_shared.core.types import SafeDateTime
    from langboard_shared.domain.models import AppResourceBinding, BoardAppBinding, GitHubHealthJob, Organization

    lifecycle, _, engine = private_receipt_storage
    if engine.dialect.name != "sqlite":
        pytest.skip("Organization fixture schema is SQLite; production PostgreSQL acceptance remains separate")
    Organization.__table__.create(engine, checkfirst=True)
    service, board, connection, payload = lifecycle
    with DbSession.atomic() as db:
        organization = Organization(name="Worker organization", slug="worker-organization", owner_user_id=board[1].id)
        db.insert(organization)
        board[2].organization_id = organization.id
        connection.ownership = "organization"
        connection.organization_id = organization.id
        db.update(board[2])
        db.update(connection)
        binding = BoardAppBinding(project_id=board[2].id, app_key="github")
        db.insert(binding)
        resource = AppResourceBinding(board_binding_id=binding.id, connection_id=connection.id,
            resource_type="repository", external_resource_id="99", access_state="granted", health="healthy",
            resource_path=[{"type": "installation", "id": "17"}, {"type": "account", "id": "7"}])
        db.insert(resource)
    body, signature = signed({"action": "unsuspend", "installation": payload["installation"]})
    receive_lifecycle(service, board[1], connection.get_uid(), body, signature, "installation", str(uuid4()))
    with DbSession.atomic() as db:
        job = db.exec(SqlBuilder.select.table(GitHubHealthJob)).first()
        if suspension == "before_query":
            organization.suspended_at = SafeDateTime.now()
            db.update(organization)
    calls = []
    def inspect(*args, **kwargs):
        calls.append(kwargs["repository_ids"])
        if suspension == "during_query":
            with DbSession.atomic() as db:
                organization.suspended_at = SafeDateTime.now()
                db.update(organization)
        return {"repositories": [{"id": 99, "archived": False}]}
    monkeypatch.setattr(resources, "inspect_installation", inspect)
    assert worker.drain_one(service, job.get_uid())
    assert len(calls) == (0 if suspension == "before_query" else 1)
    with DbSession.use(readonly=False) as db:
        current = db.exec(SqlBuilder.select.table(AppResourceBinding).where(AppResourceBinding.id == resource.id)).first()
        assert current.health == ("healthy" if suspension is None else "unavailable")
        assert current.access_state == ("granted" if suspension is None else "unknown")
        current_job = db.exec(SqlBuilder.select.table(GitHubHealthJob)).first()
        assert current_job.blocked_boards == (0 if suspension is None else 1)
        assert current_job.last_error == (None if suspension is None else "authority_unavailable")
    assert worker.drain_one(service, job.get_uid())
    with DbSession.use(readonly=False) as db:
        assert db.exec(SqlBuilder.select.table(GitHubHealthJob)).first().state == ("completed" if suspension is None else "blocked")


def test_health_job_atomic_dispatch_replay_and_paged_board_cursor(health_job, monkeypatch):
    from langboard.apps import GitHubResources as resources
    from langboard_shared.core.db import SqlBuilder
    from langboard_shared.domain.models import GitHubHealthJob

    worker, service, board, connection, job, dispatched, receive, migration, engine = health_job
    assert dispatched == [job.get_uid()]
    receive()
    assert dispatched == [job.get_uid()]
    calls = []

    def inspect(*args, **kwargs):
        calls.append(kwargs["repository_ids"])
        return {"repositories": [{"id": value, "archived": False} for value in kwargs["repository_ids"]]}

    monkeypatch.setattr(resources, "inspect_installation", inspect)
    assert worker.drain_one(service, job.get_uid())
    with DbSession.use(readonly=False) as db:
        current = db.exec(SqlBuilder.select.table(GitHubHealthJob)).first()
        assert current.project_id == 10 and current.resource_after and current.attempts == 0
    assert len(calls[0]) == 25
    assert worker.drain_one(service, job.get_uid())
    assert len(calls[1]) == 15
    # Current board authority fails for the foreign board; no API call there.
    assert worker.drain_one(service, job.get_uid())
    with DbSession.use(readonly=False) as db:
        current = db.exec(SqlBuilder.select.table(GitHubHealthJob)).first()
        assert current.state == "pending" and current.board_after == 11
        assert current.blocked_boards == 1
        assert current.last_error == "authority_unavailable"
    assert worker.drain_one(service, job.get_uid())
    with DbSession.use(readonly=False) as db:
        current = db.exec(SqlBuilder.select.table(GitHubHealthJob)).first()
        assert current.state == "blocked"
    assert len(calls) == 2 and not worker.drain_one(service, job.get_uid())


def test_health_retry_recovery_cap_and_lease_fence(health_job, monkeypatch):
    from datetime import timedelta
    from langboard_shared.core.db import SqlBuilder
    from langboard_shared.core.types import SafeDateTime
    from langboard_shared.domain.models import GitHubHealthJob

    worker, service, board, connection, job, dispatched, receive, migration, engine = health_job

    def unavailable(*args, **kwargs):
        return {"next_cursor": None, "unavailable_count": 25}

    monkeypatch.setattr(worker, "refresh_receipt_resources", unavailable)
    for attempt in range(1, 5):
        assert worker.drain_one(service, job.get_uid())
        with DbSession.use(readonly=False) as db:
            current = db.exec(SqlBuilder.select.table(GitHubHealthJob)).first()
            assert current.attempts == attempt and current.resource_after is None
            assert current.state == ("failed" if attempt == 4 else "pending")
            assert not worker.drain_one(service, job.get_uid())
            current.available_at = SafeDateTime.now() - timedelta(seconds=1)
            db.update(current)
    assert worker.recover_pending() == 0
    # Recovery after a worker crash retains cursor and counts the abandoned attempt.
    with DbSession.use(readonly=False) as db:
        current = db.exec(SqlBuilder.select.table(GitHubHealthJob)).first()
        current.state, current.attempts, current.lease_token = "processing", 1, "abandoned"
        current.available_at = SafeDateTime.now() - timedelta(seconds=1)
        db.update(current)
    dispatched.clear()
    assert worker.recover_pending(limit=1) == 1 and dispatched == [job.get_uid()]
    assert worker.drain_one(service, job.get_uid())
    with DbSession.use(readonly=False) as db:
        current = db.exec(SqlBuilder.select.table(GitHubHealthJob)).first()
        assert current.attempts == 2 and current.lease_token is None
    # Replaced lease cannot be overwritten by the old worker's completion.
    with DbSession.use(readonly=False) as db:
        current.available_at = SafeDateTime.now() - timedelta(seconds=1)
        db.update(current)

    def steal(*args, **kwargs):
        with DbSession.use(readonly=False) as db:
            current = db.exec(SqlBuilder.select.table(GitHubHealthJob)).first()
            current.lease_token = "new-worker"
            db.update(current)
        return {"next_cursor": None}

    monkeypatch.setattr(worker, "refresh_receipt_resources", steal)
    assert not worker.drain_one(service, job.get_uid())
    with DbSession.use(readonly=False) as db:
        current = db.exec(SqlBuilder.select.table(GitHubHealthJob)).first()
        assert current.lease_token == "new-worker" and current.state == "processing"


def test_health_job_rolls_back_with_receipt_and_refuses_populated_downgrade(receipt_storage, monkeypatch):
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    from langboard.apps import GitHubHealthWorker as worker
    from langboard.apps import GitHubLifecycle as lifecycle_module
    from langboard_shared.core.db import SqlBuilder
    from langboard_shared.domain.models import GitHubHealthJob, GitHubLifecycleReceipt

    lifecycle, migration, engine = receipt_storage
    service, board, connection, payload = lifecycle
    dispatched = []
    monkeypatch.setattr(worker, "enqueue", dispatched.append)
    original = lifecycle_module.schedule_receipt

    def fail(db, receipt):
        original(db, receipt)
        raise RuntimeError("after job insert")

    monkeypatch.setattr(lifecycle_module, "schedule_receipt", fail)
    body, signature = signed(payload)
    with pytest.raises(RuntimeError, match="after job"):
        lifecycle_module.receive_lifecycle(
            service, board[1], connection.get_uid(), body, signature, "installation_repositories", str(uuid4())
        )
    with DbSession.use(readonly=False) as db:
        assert not db.exec(SqlBuilder.select.table(GitHubHealthJob)).all()
        assert not db.exec(SqlBuilder.select.table(GitHubLifecycleReceipt)).all()
    assert not dispatched
    with engine.begin() as db:
        migration.health.op = Operations(MigrationContext.configure(db))
        migration.health.downgrade()
        migration.health.upgrade()
    monkeypatch.setattr(lifecycle_module, "schedule_receipt", original)
    lifecycle_module.receive_lifecycle(
        service, board[1], connection.get_uid(), body, signature, "installation_repositories", str(uuid4())
    )
    with engine.begin() as db:
        migration.health.op = Operations(MigrationContext.configure(db))
        with pytest.raises(RuntimeError, match="Cannot discard"):
            migration.health.downgrade()


def test_health_job_successful_completion_and_lost_enqueue(health_job, monkeypatch):
    from langboard_shared.core.db import SqlBuilder
    from langboard_shared.domain.models import GitHubHealthJob

    worker, service, board, connection, job, dispatched, receive, migration, engine = health_job

    def failed_enqueue(uid):
        raise RuntimeError("broker unavailable")

    monkeypatch.setattr(worker, "enqueue", failed_enqueue)
    assert worker.recover_pending() == 0
    # Both boards authorized by this test worker stub, one page each.
    monkeypatch.setattr(worker, "refresh_receipt_resources", lambda *args, **kwargs: {"next_cursor": None})
    assert worker.drain_one(service, job.get_uid())
    assert worker.drain_one(service, job.get_uid())
    assert worker.drain_one(service, job.get_uid())
    with DbSession.use(readonly=False) as db:
        current = db.exec(SqlBuilder.select.table(GitHubHealthJob)).first()
        assert current.state == "completed" and current.board_after == 11
    assert worker.recover_pending() == 0


def test_health_job_postgres_concurrent_claim_is_exclusive(health_job, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event

    worker, service, board, connection, job, dispatched, receive, migration, engine = health_job
    if engine.dialect.name != "postgresql":
        pytest.skip("PostgreSQL provides row-lock claim exclusivity")
    entered, release = Event(), Event()
    calls = []

    def inspect(*args, **kwargs):
        calls.append(args)
        entered.set()
        assert release.wait(10)
        return {"next_cursor": None}

    monkeypatch.setattr(worker, "refresh_receipt_resources", inspect)
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(worker.drain_one, service, job.get_uid())
        try:
            assert entered.wait(10)
            assert pool.submit(worker.drain_one, service, job.get_uid()).result(timeout=10) is False
        finally:
            release.set()
        assert first.result(timeout=10)
    assert len(calls) == 1


def test_health_repository_delta_never_refreshes_unrelated_repositories(health_job, monkeypatch):
    from langboard.apps import GitHubResources as resources
    from langboard.apps.GitHubLifecycle import receive_lifecycle
    from langboard_shared.core.db import SqlBuilder
    from langboard_shared.domain.models import GitHubHealthJob

    worker, service, board, connection, job, dispatched, receive, migration, engine = health_job
    payload = {
        "action": "removed",
        "installation": {"id": 17, "app_id": 42, "account": {"id": 7, "type": "Organization"}},
        "repositories_removed": [{"id": 101}],
    }
    body, signature = signed(payload)
    receive_lifecycle(
        service, board[1], connection.get_uid(), body, signature, "installation_repositories", str(uuid4())
    )
    with DbSession.use(readonly=False) as db:
        jobs = db.exec(SqlBuilder.select.table(GitHubHealthJob)).all()
        delta_job = next(item for item in jobs if item.get_uid() != job.get_uid())
    calls = []

    def inspect(*args, **kwargs):
        calls.append(kwargs["repository_ids"])
        return {"repositories": [{"id": 101, "archived": False}]}

    monkeypatch.setattr(resources, "inspect_installation", inspect)
    assert worker.drain_one(service, delta_job.get_uid())
    assert worker.drain_one(service, delta_job.get_uid())
    assert calls == [(101,)]
    with DbSession.use(readonly=False) as db:
        current = db.exec(SqlBuilder.select.table(GitHubHealthJob).where(GitHubHealthJob.id == delta_job.id)).first()
        assert current.state == "completed"


@pytest.mark.parametrize("failure", [None, "permission", "owner", "foreign_board", "invalid_cursor"])
def test_health_job_diagnostics_current_authority_paging_and_redaction(health_job, failure):
    from langboard.apps.GitHubConnections import health_jobs
    from langboard_shared.core.types import SafeDateTime
    from langboard_shared.domain.models import GitHubHealthJob, GitHubLifecycleReceipt

    worker, service, board, connection, job, dispatched, receive, migration, engine = health_job
    with DbSession.use(readonly=False) as db:
        for i in range(30):
            receipt = GitHubLifecycleReceipt(
                connection_id=connection.id,
                connection_revision="test",
                delivery_id=str(uuid4()),
                payload_digest="test",
                event="installation",
                action="created",
                app_id="42",
                installation_id="17" if i < 27 else "999",
                account_id="7",
            )
            db.insert(receipt)
            db.insert(GitHubHealthJob(receipt_id=receipt.id, available_at=SafeDateTime.now(), state="failed"))
        if failure == "permission":
            board[4].actions = ["read"]
            board[2].owner_id = 2
            db.update(board[4])
            db.update(board[2])
        elif failure == "owner":
            connection.owner_id = 2
            db.update(connection)
    if failure in {"permission", "owner", "foreign_board"}:
        with pytest.raises(GitHubManifestUnavailable):
            health_jobs(
                service, board[1], board[2].get_uid() if failure != "foreign_board" else "B", connection.get_uid()
            )
    elif failure == "invalid_cursor":
        with pytest.raises(ValueError):
            health_jobs(service, board[1], board[2].get_uid(), connection.get_uid(), "!invalid")
    else:
        first = health_jobs(service, board[1], board[2].get_uid(), connection.get_uid())
        second = health_jobs(service, board[1], board[2].get_uid(), connection.get_uid(), first["next_cursor"])
        assert len(first["items"]) == 25 and len(second["items"]) == 3 and second["next_cursor"] is None
        assert not ({item["job_uid"] for item in first["items"]} & {item["job_uid"] for item in second["items"]})
        assert all(set(item) == {"job_uid", "state"} for item in first["items"] + second["items"])


@pytest.mark.parametrize("board", ["sqlite-http"], indirect=True)
def test_health_jobs_http_requires_browser_auth_and_current_board_authority(health_job, monkeypatch):
    import importlib
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from langboard.middlewares.ApiAuthMiddleware import ApiAuthMiddleware
    from langboard.routes.board.BoardGitHubAppApi import get_github_health_jobs
    from langboard_shared.core.db.DbEngine import DbEngine
    from langboard_shared.core.routing import AppRouter
    from langboard_shared.core.security import AuthSecurity
    from langboard_shared.Env import Env

    worker, service, board, connection, job, dispatched, receive, migration, engine = health_job
    service.close = lambda: None
    monkeypatch.setattr(DbEngine, "get_readonly_engine", DbEngine.get_main_engine)
    monkeypatch.setattr(
        importlib.import_module("langboard.middlewares.ApiAuthMiddleware"), "DomainService", lambda: service
    )
    app = FastAPI()
    app.include_router(AppRouter.api)
    for route in app.routes:
        if getattr(route, "endpoint", None) == get_github_health_jobs:
            for dependency in route.dependant.dependencies:
                if dependency.name == "service":
                    app.dependency_overrides[dependency.call] = lambda: service
    app.add_middleware(ApiAuthMiddleware, routes=AppRouter.api.routes)
    access, refresh = AuthSecurity.authenticate(board[1].id)
    with TestClient(app, base_url="https://testserver") as client:
        url = f"/board/{board[2].get_uid()}/settings/apps/github/connections/{connection.get_uid()}/jobs"
        assert client.get(url).status_code == 401
        client.cookies.set(Env.REFRESH_TOKEN_NAME, refresh)
        headers = {"Authorization": f"Bearer {access}"}
        result = client.get(url, headers=headers)
        assert result.status_code == 200 and result.json()["items"] == [{"job_uid": job.get_uid(), "state": "pending"}]
        assert "secret://" not in result.text and "lease_token" not in result.text
        assert client.get(url + "?after=!invalid", headers=headers).status_code == 400
        with DbSession.use(readonly=False) as db:
            board[4].actions = ["read"]
            board[2].owner_id = 2
            db.update(board[4])
            db.update(board[2])
        assert client.get(url, headers=headers).status_code == 404
