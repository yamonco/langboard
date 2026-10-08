# ruff: noqa: F811
"""Native Vault, migrations, current board authority and signed provider check input."""
import importlib.util
from pathlib import Path
from uuid import uuid4
import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from langboard.apps.GitHubLifecycle import GitHubDeliveryConflict
from langboard.apps.GitHubManifest import GitHubManifestUnavailable
from langboard.apps.GitHubSignal import list_signals, receive_check
from langboard_shared.core.db import DbSession, SqlBuilder
from langboard_shared.core.db.DbEngine import DbEngine
from langboard_shared.domain.models import AppResourceBinding, AppSignal, BoardAppBinding
from test_github_installation import board, installation, secrets  # noqa: F401
from test_github_lifecycle import lifecycle, signed  # noqa: F401


@pytest.fixture
def signal_storage(lifecycle, monkeypatch):
    from langboard_shared.publishers import CardPublisher
    monkeypatch.setattr(CardPublisher, "put_dispather", lambda *args: None)
    service, board, connection, _ = lifecycle
    path = Path(__file__).resolve().parents[2] / "langboard/migrations/versions/20261008121000-f985238a4bc4.py"
    spec = importlib.util.spec_from_file_location("signal_migration", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    engine = DbEngine.get_main_engine()
    with engine.begin() as db:
        migration.op = Operations(MigrationContext.configure(db))
        migration.upgrade()
    with DbSession.use(readonly=False) as db:
        connection.state = "connected"
        db.update(connection)
        binding = BoardAppBinding(
            project_id=board[2].id, app_key="github", state="needs_attention", granted_capabilities=["signals.read"],
        )
        db.insert(binding)
        resource = AppResourceBinding(
            board_binding_id=binding.id, connection_id=connection.id, resource_type="repository",
            external_resource_id="99", access_state="granted", resource_path=[
                {"type": "installation", "id": "17"}, {"type": "account", "id": "7"},
                {"type": "repository", "id": "99", "name": "fixture/repo-99"},
            ],
        )
        db.insert(resource)
    payload = {
        "action": "completed", "installation": {"id": 17, "node_id": "fixture"},
        "repository": {"id": 99, "owner": {"id": 7}},
        "check_run": {"id": 55, "status": "completed", "conclusion": "success", "head_sha": "a" * 40,
                      "completed_at": "2026-10-08T00:00:00Z", "app": {"id": 999},
                      "output": {"text": "private output must not persist"}},
    }
    return service, board, connection, binding, resource, payload, migration, engine


def send(state, delivery=None):
    service, board, connection, _, resource, payload, _, _ = state
    body, signature = signed(payload)
    return receive_check(
        service, board[2].get_uid(), connection.get_uid(), resource.get_uid(), body, signature,
        "check_run", delivery or str(uuid4()),
    )


def read(state, after=None):
    service, board, connection, _, resource, _, _, _ = state
    return list_signals(service, board[1], board[2].get_uid(), connection.get_uid(), resource.get_uid(), after)


def test_signed_lite_installation_and_incomplete_mapping_keep_evidence(signal_storage):
    state = signal_storage
    delivery = str(uuid4())
    result = send(state, delivery)
    assert not result["duplicate"]
    assert send(state, delivery) == {"signal_uid": result["signal_uid"], "duplicate": True}
    items = read(state)["items"]
    assert len(items) == 1 and items[0]["commit_sha"] == "a" * 40
    assert items[0]["external_id"] == "55" and items[0]["outcome"] == "success"
    assert "private output" not in repr(items)
    state[5]["check_run"]["conclusion"] = "failure"
    with pytest.raises(GitHubDeliveryConflict):
        send(state, delivery)
    with DbSession.use(readonly=False) as db:
        assert len(db.exec(SqlBuilder.select.table(AppSignal)).all()) == 1
    assert state[3].workflow_mapping == {} and not state[3].stage_transitions_enabled


@pytest.mark.parametrize("failure", ["unlink", "access", "connection", "grant", "binding", "role", "inactive"])
def test_current_authority_blocks_ingestion_and_read(signal_storage, failure):
    state = signal_storage
    send(state)
    _, board, connection, binding, resource, _, _, _ = state
    with DbSession.use(readonly=False) as db:
        if failure == "unlink":
            resource.is_selected = False
            db.update(resource)
        elif failure == "access":
            resource.access_state = "revoked"
            db.update(resource)
        elif failure == "connection":
            connection.state = "disconnected"
            db.update(connection)
        elif failure == "grant":
            binding.granted_capabilities = []
            db.update(binding)
        elif failure == "binding":
            binding.state = "disabled"
            db.update(binding)
        elif failure == "role":
            board[4].actions = ["read"]
            db.update(board[4])
        else:
            board[1].activated_at = None
            db.update(board[1])
    with pytest.raises(GitHubManifestUnavailable):
        send(state)
    with pytest.raises(GitHubManifestUnavailable):
        read(state)


@pytest.mark.parametrize("failure", ["installation", "repository", "account", "sha", "naive", "boolean", "conclusion", "status"])
def test_provider_identity_and_timestamp_validation(signal_storage, failure):
    state = signal_storage
    payload = state[5]
    if failure == "installation":
        payload["installation"]["id"] = 18
    elif failure == "repository":
        payload["repository"]["id"] = 100
    elif failure == "account":
        payload["repository"]["owner"]["id"] = 8
    elif failure == "sha":
        payload["check_run"]["head_sha"] = "not-a-sha"
    elif failure == "naive":
        payload["check_run"]["completed_at"] = "2026-10-08T00:00:00"
    elif failure == "boolean":
        payload["check_run"]["id"] = True
    else:
        payload["check_run"][failure] = "unsupported"
    with pytest.raises(GitHubManifestUnavailable):
        send(state)


def test_pagination_and_populated_downgrade_guard(signal_storage):
    state = signal_storage
    for i in range(27):
        state[5]["check_run"]["id"] = i + 100
        send(state)
    first = read(state)
    second = read(state, first["next_cursor"])
    assert len(first["items"]) == 25 and len(second["items"]) == 2
    assert second["next_cursor"] is None
    with pytest.raises(ValueError):
        read(state, "!invalid")
    with state[7].begin() as db:
        state[6].op = Operations(MigrationContext.configure(db))
        with pytest.raises(RuntimeError, match="Cannot discard"):
            state[6].downgrade()


def test_rotation_during_signature_resolution_is_fenced(signal_storage, monkeypatch):
    state = signal_storage
    service = state[0]
    original = service.secret_reference.resolve_for_runtime
    def rotate_after(*args, **kwargs):
        from pydantic import SecretStr
        result = original(*args, **kwargs)
        uri = state[2].credential_reference
        meta = service.secret_reference.get_metadata(state[1][1], uri)
        service.secret_reference.rotate(state[1][1], uri, SecretStr('{"id":42,"webhook_secret":"rotated"}'), meta["revision"])
        return result
    monkeypatch.setattr(service.secret_reference, "resolve_for_runtime", rotate_after)
    with pytest.raises(GitHubManifestUnavailable):
        send(state)


@pytest.mark.parametrize("board", ["sqlite-http"], indirect=True)
def test_native_signed_http_and_authenticated_read(signal_storage, monkeypatch):
    import importlib
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from langboard.middlewares.ApiAuthMiddleware import ApiAuthMiddleware
    from langboard.routes.board.BoardGitHubAppApi import get_github_signals, receive_github_check
    from langboard_shared.core.routing import AppRouter
    from langboard_shared.core.security import AuthSecurity
    from langboard_shared.Env import Env

    state = signal_storage
    service, board, connection, _, resource, payload, _, _ = state
    service.close = lambda: None
    monkeypatch.setattr(DbEngine, "get_readonly_engine", DbEngine.get_main_engine)
    monkeypatch.setattr(importlib.import_module("langboard.middlewares.ApiAuthMiddleware"), "DomainService", lambda: service)
    app = FastAPI()
    app.include_router(AppRouter.api)
    app.add_middleware(ApiAuthMiddleware, routes=AppRouter.api.routes)
    for route in app.routes:
        if getattr(route, "endpoint", None) in {get_github_signals, receive_github_check}:
            for dependency in route.dependant.dependencies:
                if dependency.name == "service":
                    app.dependency_overrides[dependency.call] = lambda: service
    ingest = f"/apps/github/boards/{board[2].get_uid()}/connections/{connection.get_uid()}/resources/{resource.get_uid()}/events"
    listing = f"/board/{board[2].get_uid()}/settings/apps/github/connections/{connection.get_uid()}/resources/{resource.get_uid()}/signals"
    body, signature = signed(payload)
    headers = {"Content-Type": "application/json", "X-Hub-Signature-256": signature,
               "X-GitHub-Event": "check_run", "X-GitHub-Delivery": str(uuid4())}
    with TestClient(app, base_url="https://testserver") as client:
        assert client.get(listing).status_code == 401
        assert client.post(ingest, content=body, headers=headers).status_code == 202
        assert client.post(ingest, content=body, headers=headers).status_code == 202
        assert client.post(ingest, content=body + b" ", headers=headers).status_code == 400
        assert client.post(ingest, content=body, headers={**headers, "Content-Encoding": "gzip"}).status_code == 415
        assert client.post(ingest, content=body, headers=list(headers.items()) + [("X-GitHub-Event", "ping")]).status_code == 400
        payload["check_run"]["conclusion"] = "failure"
        changed, changed_signature = signed(payload)
        assert client.post(ingest, content=changed, headers={**headers, "X-Hub-Signature-256": changed_signature}).status_code == 409
        access, refresh = AuthSecurity.authenticate(board[1].id)
        client.cookies.set(Env.REFRESH_TOKEN_NAME, refresh)
        result = client.get(listing, headers={"Authorization": f"Bearer {access}"})
        assert result.status_code == 200 and len(result.json()["items"]) == 1
        assert "private output" not in result.text and "payload_digest" not in result.text
        with DbSession.use(readonly=False) as db:
            resource.is_selected = False
            db.update(resource)
        assert client.get(listing, headers={"Authorization": f"Bearer {access}"}).status_code == 404
        assert client.post(ingest, content=body, headers=headers).status_code == 400


@pytest.mark.parametrize("failure", ["unlink", "path", "secret_revoke"])
def test_authority_changes_during_signature_resolution_block_commit(signal_storage, monkeypatch, failure):
    state = signal_storage
    original = state[0].secret_reference.resolve_for_runtime
    def change_after(*args, **kwargs):
        result = original(*args, **kwargs)
        if failure == "secret_revoke":
            state[0].secret_reference.revoke(
                state[1][1], state[2].credential_reference,
                state[0].secret_reference.get_metadata(state[1][1], state[2].credential_reference)["revision"],
            )
        else:
            with DbSession.use(readonly=False) as db:
                if failure == "unlink":
                    state[4].is_selected = False
                else:
                    state[4].resource_path = [{"type": "installation", "id": "18"}, *state[4].resource_path[1:]]
                db.update(state[4])
        return result
    monkeypatch.setattr(state[0].secret_reference, "resolve_for_runtime", change_after)
    with pytest.raises(GitHubManifestUnavailable):
        send(state)
    if failure == "secret_revoke":
        assert state[0].secret_reference.get_metadata(state[1][1], state[2].credential_reference)["state"] == "revoked"
    with DbSession.use(readonly=False) as db:
        assert not db.exec(SqlBuilder.select.table(AppSignal)).all()


def test_postgres_concurrent_redelivery_commits_once(signal_storage, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    from langboard.apps import GitHubSignal
    state = signal_storage
    if state[7].dialect.name != "postgresql":
        pytest.skip("PostgreSQL row-lock proof")
    original = GitHubSignal.verify_signed_payload
    barrier = Barrier(2)
    def synchronize(*args, **kwargs):
        result = original(*args, **kwargs)
        barrier.wait(timeout=10)
        return result
    monkeypatch.setattr(GitHubSignal, "verify_signed_payload", synchronize)
    delivery = str(uuid4())
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: send(state, delivery), range(2)))
    assert results[0]["signal_uid"] == results[1]["signal_uid"]
    assert sorted(item["duplicate"] for item in results) == [False, True]
    assert len(read(state)["items"]) == 1


def test_secret_revocation_blocks_existing_check_listing(signal_storage):
    state = signal_storage
    send(state)
    service = state[0].secret_reference
    uri = state[2].credential_reference
    service.revoke(state[1][1], uri, service.get_metadata(state[1][1], uri)['revision'])
    with pytest.raises(GitHubManifestUnavailable):
        read(state)


def test_signal_notification_is_commit_only_minimal_and_duplicate_free(signal_storage, monkeypatch):
    from langboard_shared.core.routing import SocketTopic
    from langboard_shared.publishers import CardPublisher
    state = signal_storage
    notifications = []
    def capture(payload, message):
        with DbSession.use(readonly=False) as db:
            assert db.exec(SqlBuilder.select.table(AppSignal)).first() is not None
        assert payload == {'app_signal_changed': True}
        assert message.topic == SocketTopic.Board
        assert message.topic_id == state[1][2].get_uid()
        assert message.event == 'board:app-signal:changed'
        assert message.data_keys == 'app_signal_changed' and message.custom_data is None
        notifications.append(payload)
    monkeypatch.setattr(CardPublisher, 'put_dispather', capture)
    delivery = str(uuid4())
    with pytest.raises(RuntimeError, match='rollback fixture'):
        with DbSession.atomic():
            send(state, delivery)
            assert notifications == []
            raise RuntimeError('rollback fixture')
    assert notifications == []
    send(state, delivery)
    assert len(notifications) == 1
    send(state, delivery)
    assert len(notifications) == 1


def test_notification_transport_failure_preserves_committed_evidence(signal_storage, monkeypatch):
    from langboard_shared.publishers import CardPublisher
    def unavailable(*args):
        raise RuntimeError('disposable transport failure')
    monkeypatch.setattr(CardPublisher, 'app_signal_changed', unavailable)
    result = send(signal_storage)
    assert not result['duplicate']
    assert len(read(signal_storage)['items']) == 1
