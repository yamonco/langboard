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
def test_lifecycle_invalidates_only_matching_selected_resources(receipt_storage, action):
    from langboard.apps.GitHubLifecycle import receive_lifecycle
    from langboard.apps.GitHubResources import resource_snapshot
    from langboard_shared.core.db import SqlBuilder
    from langboard_shared.domain.models import AppResourceBinding, BoardAppBinding, GitHubLifecycleReceipt

    lifecycle, migration, engine = receipt_storage
    service, board, connection, payload = lifecycle
    with DbSession.use(readonly=False) as db:
        bindings = []
        for project_id in (10, 11):
            binding = BoardAppBinding(project_id=project_id, app_key="github")
            db.insert(binding)
            bindings.append(binding)
        resources = []
        for index, (binding, installation_id, account_id, selected, repo) in enumerate(
            [
                (bindings[0], 17, 7, True, 99),
                (bindings[1], 17, 7, True, 99),
                (bindings[0], 18, 7, True, 100),
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
    first = receive_lifecycle(service, board[1], connection.get_uid(), body, signature, event, delivery)
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


@pytest.mark.parametrize("failure", [None, "permission", "ping", "owner_inactive", "connection_changed"])
def test_receipt_refresh_revalidates_authority_and_scopes_installation(receipt_storage, monkeypatch, failure):
    from langboard.apps import GitHubResources as resources
    from langboard.apps.GitHubHealth import refresh_receipt_resources
    from langboard.apps.GitHubLifecycle import receive_lifecycle
    from langboard_shared.core.db import SqlBuilder
    from langboard_shared.domain.models import AppResourceBinding, BoardAppBinding

    lifecycle, migration, engine = receipt_storage
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
            db.update(board[4])
        elif failure == "connection_changed":
            connection.external_account_id = "43"
            db.update(connection)
        elif failure == "owner_inactive":
            board[1].activated_at = None
            db.update(board[1])
    calls = []

    def inspect(*args, **kwargs):
        calls.append((args, kwargs))
        assert args[4] == 17 and kwargs["repository_ids"] == (17,)
        return {"repositories": [{"id": 17, "archived": False}]}

    monkeypatch.setattr(resources, "inspect_installation", inspect)
    if failure:
        with pytest.raises(GitHubManifestUnavailable):
            refresh_receipt_resources(service, receipt["receipt_uid"], board[2].get_uid())
        assert not calls
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


def test_receipt_refresh_is_limited_to_25_resource_pages(receipt_storage, monkeypatch):
    from langboard.apps import GitHubResources as resources
    from langboard.apps.GitHubHealth import refresh_receipt_resources
    from langboard.apps.GitHubLifecycle import receive_lifecycle
    from langboard_shared.domain.models import AppResourceBinding, BoardAppBinding

    lifecycle, migration, engine = receipt_storage
    service, board, connection, payload = lifecycle
    with DbSession.use(readonly=False) as db:
        binding = BoardAppBinding(project_id=board[2].id, app_key="github")
        db.insert(binding)
        for i in range(40):
            db.insert(
                AppResourceBinding(
                    board_binding_id=binding.id,
                    connection_id=connection.id,
                    resource_type="repository",
                    external_resource_id=str(100 + i),
                    resource_path=[{"type": "installation", "id": "17"}, {"type": "account", "id": "7"}],
                )
            )
    body, signature = signed({"action": "created", "installation": payload["installation"]})
    receipt = receive_lifecycle(service, board[1], connection.get_uid(), body, signature, "installation", str(uuid4()))
    sizes = []

    def inspect(*args, **kwargs):
        ids = kwargs["repository_ids"]
        sizes.append(len(ids))
        return {"repositories": [{"id": uid, "archived": False} for uid in ids]}

    monkeypatch.setattr(resources, "inspect_installation", inspect)
    first = refresh_receipt_resources(service, receipt["receipt_uid"], board[2].get_uid())
    assert first["refreshed_count"] == 25 and first["next_cursor"]
    second = refresh_receipt_resources(service, receipt["receipt_uid"], board[2].get_uid(), first["next_cursor"])
    assert second["refreshed_count"] == 15 and second["next_cursor"] is None and sizes == [25, 15]


def test_receipt_refresh_fences_connection_changed_between_snapshot_and_query(receipt_storage, monkeypatch):
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
    snapshot = health.get_resources

    def change(*args):
        result = snapshot(*args)
        with DbSession.use(readonly=False) as db:
            connection.external_account_id = "43"
            db.update(connection)
        return result

    monkeypatch.setattr(health, "get_resources", change)
    with pytest.raises(GitHubResourceConflict):
        health.refresh_receipt_resources(service, receipt["receipt_uid"], board[2].get_uid())
