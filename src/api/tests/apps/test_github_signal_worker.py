# ruff: noqa: F811
"""Native shared webhook dispatch with durable, bounded current-authority fanout."""
import importlib.util
from pathlib import Path
from uuid import uuid4
import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from langboard.apps import GitHubSignalWorker as worker
from langboard.apps.GitHubLifecycle import GitHubDeliveryConflict
from langboard.apps.GitHubManifest import GitHubManifestUnavailable
from langboard_shared.core.db import DbSession, SqlBuilder
from langboard_shared.core.types import SafeDateTime
from langboard_shared.domain.models import (
    AppConnection,
    AppDefinition,
    AppResourceBinding,
    AppSignal,
    BoardAppBinding,
    GitHubSignalDelivery,
    Organization,
    Project,
)
from test_github_installation import board, installation, secrets  # noqa: F401
from test_github_lifecycle import lifecycle, signed  # noqa: F401
from test_github_signal import signal_storage  # noqa: F401


@pytest.fixture
def delivery_storage(signal_storage, monkeypatch):
    state = signal_storage
    with DbSession.atomic() as db:
        organization = Organization(name="Delivery fixture", slug="delivery-fixture", owner_user_id=state[1][1].id)
        db.insert(organization)
        state[1][2].organization_id = organization.id
        state[2].ownership = "organization"
        state[2].organization_id = organization.id
        db.update(state[1][2])
        db.update(state[2])
    path = Path(__file__).resolve().parents[2] / "langboard/migrations/versions/20261008123000-0a96349b5cd5.py"
    spec = importlib.util.spec_from_file_location("signal_delivery_migration", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    with state[7].begin() as db:
        migration.op = Operations(MigrationContext.configure(db))
        # Current ORM fixtures include the new index; reconstruct the preceding deployed schema.
        migration.op.drop_index("ix_app_resource_signal_lookup", table_name="app_resource_binding")
        migration.upgrade()
    queued = []
    monkeypatch.setattr(worker, "enqueue", queued.append)
    return state, queued, migration


def receive(fixture, delivery=None):
    state = fixture[0]
    body, signature = signed(state[5])
    return worker.receive_external_check(state[0], body, signature, "check_run", delivery or str(uuid4()), "42")


def job(uid):
    from langboard_shared.helpers import InfraHelper
    with DbSession.use(readonly=False) as db:
        return db.exec(SqlBuilder.select.table(GitHubSignalDelivery).where(GitHubSignalDelivery.id == InfraHelper.convert_id(uid))).first()


def evidence():
    with DbSession.use(readonly=False) as db:
        return db.exec(SqlBuilder.select.table(AppSignal)).all()


def add_board(state, project_id, *, grant=True, repository="99"):
    with DbSession.use(readonly=False) as db:
        project = Project(owner_id=state[1][1].id, organization_id=state[1][2].organization_id, title=f"Fanout fixture {project_id}")
        db.insert(project)
        binding = BoardAppBinding(project_id=project.id, app_key="github", state="needs_attention", granted_capabilities=["signals.read"] if grant else [])
        db.insert(binding)
        resource = AppResourceBinding(board_binding_id=binding.id, connection_id=state[2].id,
            resource_type="repository", external_resource_id=repository, access_state="granted",
            resource_path=[{"type":"installation","id":"17"},{"type":"account","id":"7"},
                           {"type":"repository","id":repository}])
        db.insert(resource)
    return project, binding, resource


def test_multi_board_delivery_durable_paging_and_no_mapping_requirement(delivery_storage):
    state, queued, _ = delivery_storage
    for i in range(5):
        add_board(state, 100 + i)
    add_board(state, 201, repository="100")
    result = receive(delivery_storage)
    uid = result["delivery_uid"]
    assert queued == [uid] and not evidence()
    for expected in range(1, 7):
        assert worker.drain_one(state[0], uid)
        assert len(evidence()) == expected
        assert job(uid).state == "pending"
    assert worker.drain_one(state[0], uid)
    assert job(uid).state == "completed" and len(evidence()) == 6
    assert not worker.drain_one(state[0], uid)


@pytest.mark.parametrize("scope", ["shared-personal", "private-personal", "inactive-organization", "suspended-organization"])
def test_delivery_rechecks_unattended_connection_scope(delivery_storage, scope):
    state = delivery_storage[0]
    uid = receive(delivery_storage)["delivery_uid"]
    with DbSession.atomic() as db:
        if scope.endswith("personal"):
            state[2].ownership = "personal"
            state[2].organization_id = None
        if scope == "private-personal":
            state[1][2].organization_id = None
            state[1][2].owner_id = state[1][1].id
            db.update(state[1][2])
        elif scope.endswith("organization"):
            organization = db.exec(SqlBuilder.select.table(Organization).where(Organization.id == state[2].organization_id)).first()
            if scope == "inactive-organization":
                organization.is_active = False
            else:
                organization.suspended_at = SafeDateTime.now()
            db.update(organization)
        db.update(state[2])
        # Store the current revision so this exercises ownership, not the revision fence.
        from langboard.apps.GitHubInstallation import connection_revision
        delivery = job(uid)
        delivery.connection_revision = connection_revision(state[2])
        db.update(delivery)
    assert worker.drain_one(state[0], uid)
    if scope == "private-personal":
        assert len(evidence()) == 1
        assert job(uid).skipped_resources == 0
    else:
        assert evidence() == []
        assert job(uid).skipped_resources == 1
        assert job(uid).last_error == "authority_unavailable"
    assert all(row.outcome == "success" and row.commit_sha == "a" * 40 for row in evidence())
    assert "private output" not in repr(job(uid).evidence)


def test_replay_and_conflict_do_not_duplicate_jobs(delivery_storage):
    delivery = str(uuid4())
    first = receive(delivery_storage, delivery)
    assert receive(delivery_storage, delivery) == {"delivery_uid": first["delivery_uid"], "duplicate": True}
    assert len(delivery_storage[1]) == 1
    delivery_storage[0][5]["check_run"]["conclusion"] = "failure"
    with pytest.raises(GitHubDeliveryConflict):
        receive(delivery_storage, delivery)


@pytest.mark.parametrize("failure", ["target", "ambiguous", "tamper", "inactive", "rotation"])
def test_shared_routing_is_bounded_and_signature_authorized(delivery_storage, monkeypatch, failure):
    state = delivery_storage[0]
    body, signature = signed(state[5])
    target = "43" if failure == "target" else "42"
    if failure == "tamper":
        body += b" "
    elif failure == "ambiguous":
        with DbSession.use(readonly=False) as db:
            db.insert(AppConnection(app_key="github", external_account_id="42", owner_id=state[1][1].id, state="connected"))
    elif failure == "inactive":
        with DbSession.use(readonly=False) as db:
            state[1][1].activated_at = None
            db.update(state[1][1])
    elif failure == "rotation":
        original = state[0].secret_reference.resolve_for_runtime
        def rotate_after(*args, **kwargs):
            from pydantic import SecretStr
            result = original(*args, **kwargs)
            uri = state[2].credential_reference
            meta = state[0].secret_reference.get_metadata(state[1][1], uri)
            state[0].secret_reference.rotate(state[1][1], uri, SecretStr('{"id":42,"webhook_secret":"changed"}'), meta["revision"])
            return result
        monkeypatch.setattr(state[0].secret_reference, "resolve_for_runtime", rotate_after)
    with pytest.raises(GitHubManifestUnavailable):
        worker.receive_external_check(state[0], body, signature, "check_run", str(uuid4()), target)
    assert not delivery_storage[1] and not evidence()


@pytest.mark.parametrize("failure", ["grant", "unlink", "role", "connection", "secret", "path"])
def test_revoked_target_is_skipped_without_harming_other_board(delivery_storage, failure):
    state = delivery_storage[0]
    add_board(state, 100)
    uid = receive(delivery_storage)["delivery_uid"]
    with DbSession.use(readonly=False) as db:
        if failure == "grant":
            state[3].granted_capabilities = []
            db.update(state[3])
        elif failure == "unlink":
            state[4].is_selected = False
            db.update(state[4])
        elif failure == "role":
            state[1][4].actions = ["read"]
            db.update(state[1][4])
        elif failure == "connection":
            state[2].state = "disconnected"
            db.update(state[2])
        elif failure == "path":
            state[4].resource_path = [{"type":"installation","id":"17"},{"type":"account","id":"7"},{"type":"repository","id":"100"}]
            db.update(state[4])
    if failure == "secret":
        state[0].secret_reference.revoke(
            state[1][1], state[2].credential_reference,
            state[0].secret_reference.get_metadata(state[1][1], state[2].credential_reference)["revision"],
        )
    # One claim per resource. Global revocation rejects all targets.
    for _ in range(6):
        worker.drain_one(state[0], uid)
        if job(uid).state in {"completed", "blocked", "failed"}:
            break
    expected = 0 if failure in {"connection", "secret"} else 1
    assert len(evidence()) == expected
    assert job(uid).state == "blocked"


def test_resource_created_after_delivery_is_not_added_to_fanout(delivery_storage):
    state = delivery_storage[0]
    uid = receive(delivery_storage)["delivery_uid"]
    add_board(state, 100)
    worker.drain_one(state[0], uid)
    worker.drain_one(state[0], uid)
    assert len(evidence()) == 1 and job(uid).state == "completed"


def test_lost_dispatch_recovered_and_populated_downgrade_guard(delivery_storage, monkeypatch):
    state, _, migration = delivery_storage
    monkeypatch.setattr(worker, "enqueue", lambda _: (_ for _ in ()).throw(RuntimeError("queue offline")))
    uid = receive(delivery_storage)["delivery_uid"]
    assert job(uid).state == "pending"
    assert worker.recover_pending() == 0
    queued = []
    monkeypatch.setattr(worker, "enqueue", queued.append)
    assert worker.recover_pending() == 1 and queued == [uid]
    with state[7].begin() as db:
        migration.op = Operations(MigrationContext.configure(db))
        with pytest.raises(RuntimeError, match="Cannot discard"):
            migration.downgrade()


def test_expired_lease_replay_keeps_one_event(delivery_storage):
    from datetime import timedelta
    state = delivery_storage[0]
    uid = receive(delivery_storage)["delivery_uid"]
    with DbSession.use(readonly=False) as db:
        current = job(uid)
        current.state, current.lease_token = "processing", "expired-claim"
        current.available_at = SafeDateTime.now() - timedelta(seconds=1)
        db.update(current)
    assert worker.recover_pending() == 1
    worker.drain_one(state[0], uid)
    assert len(evidence()) == 1 and job(uid).lease_token is None
    worker.drain_one(state[0], uid)
    assert job(uid).state == "completed"


@pytest.mark.parametrize("board", ["sqlite-http"], indirect=True)
def test_global_webhook_routes_check_delivery_without_browser_auth(delivery_storage, monkeypatch):
    import importlib
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from langboard.middlewares.ApiAuthMiddleware import ApiAuthMiddleware
    from langboard.routes.board.BoardGitHubAppApi import receive_github_lifecycle
    from langboard_shared.core.routing import AppRouter
    state = delivery_storage[0]
    service = state[0]
    service.close = lambda: None
    monkeypatch.setattr(importlib.import_module("langboard.middlewares.ApiAuthMiddleware"), "DomainService", lambda: service)
    app = FastAPI()
    app.include_router(AppRouter.api)
    app.add_middleware(ApiAuthMiddleware, routes=AppRouter.api.routes)
    for route in app.routes:
        if getattr(route, "endpoint", None) is receive_github_lifecycle:
            for dependency in route.dependant.dependencies:
                if dependency.name == "service":
                    app.dependency_overrides[dependency.call] = lambda: service
    body, signature = signed(state[5])
    headers = {"Content-Type":"application/json", "X-Hub-Signature-256":signature,
               "X-GitHub-Event":"check_run", "X-GitHub-Delivery":str(uuid4()),
               "X-GitHub-Hook-Installation-Target-ID":"42"}
    with TestClient(app) as client:
        assert client.post("/apps/github/events", content=body, headers=headers).status_code == 202
        assert client.post("/apps/github/events", content=body, headers=headers).status_code == 202
        assert len(delivery_storage[1]) == 1
        assert client.post("/apps/github/events", content=body + b" ", headers=headers).status_code == 400
        assert client.post("/apps/github/events", content=body, headers={**headers,"X-GitHub-Hook-Installation-Target-ID":"999"}).status_code == 400
        assert client.post("/apps/github/events", content=body, headers={**headers,"Content-Encoding":"gzip"}).status_code == 415
    uid = delivery_storage[1][0]
    assert not evidence()
    worker.drain_one(service, uid)
    worker.drain_one(service, uid)
    assert len(evidence()) == 1 and job(uid).state == "completed"


def test_processing_retry_cap_and_stale_lease_cannot_write(delivery_storage, monkeypatch):
    from datetime import timedelta
    state = delivery_storage[0]
    uid = receive(delivery_storage)["delivery_uid"]
    original = worker._scope
    monkeypatch.setattr(worker, "_scope", lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("database unavailable")))
    for attempt in range(1, 5):
        worker.drain_one(state[0], uid)
        assert job(uid).attempts == attempt
        assert job(uid).state == ("failed" if attempt == 4 else "pending")
        assert not evidence()
        if attempt < 4:
            with DbSession.use(readonly=False) as db:
                current = job(uid)
                current.available_at = SafeDateTime.now() - timedelta(seconds=1)
                db.update(current)
    assert worker.recover_pending() == 0
    state[5]["check_run"]["id"] = 56
    uid = receive(delivery_storage)["delivery_uid"]
    def steal_after(*args, **kwargs):
        result = original(*args, **kwargs)
        with DbSession.use(readonly=False) as db:
            current = job(uid)
            current.lease_token = "new-worker-token"
            db.update(current)
        return result
    monkeypatch.setattr(worker, "_scope", steal_after)
    assert not worker.drain_one(state[0], uid)
    assert not evidence()


def test_existing_resource_evidence_is_reused_by_shared_dispatch(delivery_storage):
    from test_github_signal import send
    state = delivery_storage[0]
    delivery = str(uuid4())
    direct = send(state, delivery)
    uid = receive(delivery_storage, delivery)["delivery_uid"]
    worker.drain_one(state[0], uid)
    worker.drain_one(state[0], uid)
    assert len(evidence()) == 1 and evidence()[0].get_uid() == direct["signal_uid"]
    assert job(uid).state == "completed"


def test_postgres_concurrent_claim_excludes_second_worker(delivery_storage, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event
    state = delivery_storage[0]
    if state[7].dialect.name != "postgresql":
        pytest.skip("PostgreSQL concurrent lease proof")
    uid = receive(delivery_storage)["delivery_uid"]
    original = worker._scope
    entered, release = Event(), Event()
    def hold(*args, **kwargs):
        entered.set()
        assert release.wait(timeout=10)
        return original(*args, **kwargs)
    monkeypatch.setattr(worker, "_scope", hold)
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(worker.drain_one, state[0], uid)
        assert entered.wait(timeout=10)
        second = pool.submit(worker.drain_one, state[0], uid)
        try:
            assert second.result(timeout=5) is False
        finally:
            release.set()
        assert first.result(timeout=5) is True
    assert len(evidence()) == 1


def test_postgres_concurrent_shared_redelivery_creates_one_job(delivery_storage, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    state = delivery_storage[0]
    if state[7].dialect.name != "postgresql":
        pytest.skip("PostgreSQL shared receipt lock proof")
    original = worker.verify_signed_payload
    barrier = Barrier(2)
    def hold(*args, **kwargs):
        result = original(*args, **kwargs)
        barrier.wait(timeout=10)
        return result
    monkeypatch.setattr(worker, "verify_signed_payload", hold)
    delivery = str(uuid4())
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: receive(delivery_storage, delivery), range(2)))
    assert results[0]["delivery_uid"] == results[1]["delivery_uid"]
    assert sorted(item["duplicate"] for item in results) == [False, True]
    assert len(delivery_storage[1]) == 1


def test_api_broker_registers_and_dispatches_signal_task_without_shared_api_dependency():
    import os
    import subprocess
    import sys
    script = '''
from langboard_shared.core.broker import Broker
Broker.celery.conf.update(broker_url="memory://", task_always_eager=True, task_eager_propagates=True)
from langboard.commands.RunBrokerCommand import RunBrokerCommand
Broker.start = lambda argv: None
RunBrokerCommand().execute(None)
from langboard.apps import GitHubHealthTask, GitHubSignalWorker
calls = []
class Service:
    def close(self): calls.append("closed")
GitHubHealthTask.DomainService = Service
GitHubSignalWorker.drain_one = lambda service, uid: calls.append(uid)
assert "langboard.apps.GitHubHealthTask.github_signal_task" in Broker.celery.tasks
GitHubHealthTask.github_signal_task("fixture-delivery")
assert calls == ["fixture-delivery", "closed"], calls
def fail(service, uid): raise RuntimeError("worker failure")
GitHubSignalWorker.drain_one = fail
try: GitHubHealthTask.github_signal_task("fixture-delivery")
except RuntimeError: pass
else: raise AssertionError("worker failure swallowed")
assert calls == ["fixture-delivery", "closed", "closed"], calls
'''
    result = subprocess.run(
        [sys.executable, "-c", script], env={**os.environ, "CACHE_TYPE": "redis", "CACHE_URL": "redis://127.0.0.1:6379/0", "BROKER_URL": "memory://"},
        capture_output=True, text=True, timeout=20,
    )
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.parametrize("action", ["created", "rerequested", "requested_action"])
def test_signed_noncompletion_actions_are_acknowledged_without_retry_storm(delivery_storage, action):
    state = delivery_storage[0]
    state[5]["action"] = action
    assert receive(delivery_storage) == {"ignored": True}
    assert not evidence() and not delivery_storage[1]


def test_worker_notifies_only_after_new_resource_evidence_commit(delivery_storage, monkeypatch):
    from langboard_shared.publishers import CardPublisher
    state = delivery_storage[0]
    notified = []
    def capture(project_uid):
        assert evidence()
        notified.append(project_uid)
    monkeypatch.setattr(CardPublisher, 'app_signal_changed', capture)
    uid = receive(delivery_storage)['delivery_uid']
    assert notified == []
    assert worker.drain_one(state[0], uid)
    assert notified == [state[1][2].get_uid()]
    assert worker.drain_one(state[0], uid)
    assert notified == [state[1][2].get_uid()]


@pytest.mark.parametrize("change", ["disabled", "capability"])
def test_queued_signal_does_not_execute_after_app_revocation(delivery_storage, change):
    state = delivery_storage[0]
    result = receive(delivery_storage)
    uid = result["delivery_uid"]
    before = dict(job(uid).evidence)
    with DbSession.atomic() as db:
        definition = db.exec(SqlBuilder.select.table(AppDefinition).where(AppDefinition.key == "github")).first()
        if change == "disabled":
            definition.is_enabled = False
            db.update(definition)
        else:
            definition.declaration = {"capabilities": []}
            db.update(definition)
    assert worker.drain_one(state[0], uid)
    assert not evidence()
    assert job(uid).last_error == "authority_unavailable"
    assert worker.drain_one(state[0], uid)
    assert job(uid).state == "blocked"
    assert job(uid).evidence == before
