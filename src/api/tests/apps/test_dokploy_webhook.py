# ruff: noqa: F811
import importlib
import json
import pytest
from langboard.apps import DokployConnection as dk
from langboard.apps import DokployWebhook as webhook
from langboard_shared.core.db import DbSession, SqlBuilder
from langboard_shared.core.db.DbEngine import DbEngine
from langboard_shared.domain.models import (
    AppConnection,
    AppResourceBinding,
    AppSignal,
    BoardAppBinding,
    DokployNotificationReceipt,
    DokployWebhookBinding,
    SecretReference,
    User,
)
from langboard_shared.domain.services.factory.SecretReferenceService_test import secrets  # noqa: F401
from langboard_shared.domain.services.factory.WorkflowStageService_app_test import board  # noqa: F401
from pydantic import SecretStr
from test_dokploy_connection import connect, setup  # noqa: F401


BODY = json.dumps({"type": "build", "status": "success", "applicationName": "private", "timestamp": "old"}).encode()


@pytest.fixture
def configured(setup):
    service, board, *_ = setup
    for model in (DokployWebhookBinding, DokployNotificationReceipt, AppSignal):
        model.__table__.create(DbEngine.get_main_engine(), checkfirst=True)
    conn = connect(setup)
    dk.bind_resource(
        service,
        board[1],
        board[2].get_uid(),
        conn["connection_uid"],
        "application",
        "app-1",
        "project-1",
        "env-1",
        conn["revision"],
    )
    with DbSession.use(readonly=False) as db:
        binding = db.exec(SqlBuilder.select.table(BoardAppBinding)).first()
        revision = binding.edit_revision()
    dk.enable_read_access(service, board[1], board[2].get_uid(), conn["connection_uid"], conn["revision"], revision)
    reference = service.secret_reference.create(
        board[1], "personal", "me", "dokploy/webhook", SecretStr("receiver-token")
    )
    before = webhook.health(service, board[1], board[2].get_uid(), conn["connection_uid"])
    assert before["state"] == "unconfigured" and before["last_received_at"] is None
    config = webhook.configure(
        service,
        board[1],
        board[2].get_uid(),
        conn["connection_uid"],
        conn["revision"],
        before["binding_revision"],
        0,
        reference["uri"],
    )
    return setup, conn, reference, config


def accept(configured, body=BODY, authorization="Bearer receiver-token"):
    service = configured[0][0]
    config = configured[3]
    revision = webhook.authenticate(service, config["config_uid"], authorization)
    return webhook.receive(service, config["config_uid"], authorization, body, revision)


def test_durable_minimal_deduplicated_health_no_provider_io(configured):
    setup, conn, _, config = configured
    count = len(setup[3])
    first = accept(configured)
    again = accept(configured)
    assert again == {**first, "duplicate": True}
    assert not first["duplicate"] and len(setup[3]) == count
    health = webhook.health(setup[0], setup[1][1], setup[1][2].get_uid(), conn["connection_uid"])
    assert health["last_received_at"] == first["received_at"] and health["provider_config"] == "unknown"
    assert "receiver-token" not in json.dumps(health)
    with DbSession.use(readonly=False) as db:
        rows = db.exec(SqlBuilder.select.table(DokployNotificationReceipt)).all()
        assert len(rows) == 1 and "private" not in json.dumps(rows[0].model_dump(), default=str)
        assert not db.exec(SqlBuilder.select.table(AppSignal)).all()
    webhook.disable(
        setup[0],
        setup[1][1],
        setup[1][2].get_uid(),
        conn["connection_uid"],
        conn["revision"],
        config["binding_revision"],
        config["config_revision"],
    )
    with pytest.raises(dk.DokployUnavailable):
        accept(configured)
    assert (
        webhook.health(setup[0], setup[1][1], setup[1][2].get_uid(), conn["connection_uid"])["last_received_at"]
        == first["received_at"]
    )


@pytest.mark.parametrize(
    "failure", ["role", "owner", "inactive", "connection", "binding", "resource", "revision", "secret", "rotation"]
)
def test_current_authority_and_fences_no_receipts(configured, failure):
    setup, _, reference, _ = configured
    with DbSession.use(readonly=False) as db:
        if failure == "role":
            setup[1][4].actions = ["read"]
            db.update(setup[1][4])
        elif failure in {"owner", "inactive", "connection"}:
            row = db.exec(SqlBuilder.select.table(AppConnection)).first()
            if failure == "owner":
                row.owner_id = 2
            elif failure == "inactive":
                user = db.exec(SqlBuilder.select.table(User).where(User.id == row.owner_id)).first()
                user.activated_at = None
                db.update(user)
            else:
                row.state = "disconnected"
            db.update(row)
        elif failure == "binding":
            row = db.exec(SqlBuilder.select.table(BoardAppBinding)).first()
            row.granted_capabilities = []
            db.update(row)
        elif failure in {"resource", "revision"}:
            row = db.exec(SqlBuilder.select.table(AppResourceBinding)).first()
            if failure == "resource":
                row.is_selected = False
            else:
                row.access_revision += 1
            db.update(row)
        else:
            from langboard_shared.helpers import InfraHelper

            row = db.exec(
                SqlBuilder.select.table(SecretReference).where(
                    SecretReference.id == InfraHelper.convert_id(reference["uri"].rsplit("/", 1)[1])
                )
            ).first()
            if failure == "secret":
                row.state = "revoked"
            else:
                row.revision += 1
            db.update(row)
    from langboard_shared.domain.services.factory.SecretReferenceService import SecretReferenceUnavailable

    with pytest.raises((dk.DokployUnavailable, SecretReferenceUnavailable)):
        accept(configured)
    with DbSession.use(readonly=False) as db:
        assert not db.exec(SqlBuilder.select.table(DokployNotificationReceipt)).all()


@pytest.mark.parametrize(
    "body",
    [
        b"no",
        b"[]",
        b'{"type":"other","status":"success"}',
        b'{"type":"build","status":[]}',
        b'{"type":"build","type":"build","status":"success"}',
        b'{"type":"build","status":"success","message":{}}',
        b" " * 65537,
        json.dumps({"type": "build", "status": "success", "message": "x" * 8193}).encode(),
    ],
    ids=[
        "invalid-json",
        "array",
        "unsupported",
        "invalid-status",
        "duplicate-field",
        "nested",
        "oversize",
        "long-string",
    ],
)
def test_bounded_malformed_payload_no_partial_receipt(configured, body):
    with pytest.raises(ValueError):
        accept(configured, body)
    with DbSession.use(readonly=False) as db:
        assert not db.exec(SqlBuilder.select.table(DokployNotificationReceipt)).all()


def test_stale_config_and_management_secret_reuse_rejected(configured):
    setup, conn, _, config = configured
    with pytest.raises(dk.DokployConflict):
        webhook.configure(
            setup[0],
            setup[1][1],
            setup[1][2].get_uid(),
            conn["connection_uid"],
            conn["revision"],
            config["binding_revision"],
            0,
            setup[2]["uri"],
        )
    with pytest.raises(ValueError):
        webhook.configure(
            setup[0],
            setup[1][1],
            setup[1][2].get_uid(),
            conn["connection_uid"],
            conn["revision"],
            config["binding_revision"],
            1,
            setup[2]["uri"],
        )
    with pytest.raises(dk.DokployUnavailable):
        webhook.receive(setup[0], config["config_uid"], "Bearer receiver-token", BODY, 0)


@pytest.mark.parametrize("board", ["sqlite-http"], indirect=True)
def test_native_receiver_bearer_only_uniform_failure(configured, monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from langboard.middlewares.ApiAuthMiddleware import ApiAuthMiddleware
    from langboard.routes.board import BoardDokployAppApi as api
    from langboard_shared.core.routing import AppRouter

    setup, _, _, config = configured
    service = setup[0]
    service.close = lambda: None
    monkeypatch.setattr(DbEngine, "get_readonly_engine", DbEngine.get_main_engine)
    monkeypatch.setattr(
        importlib.import_module("langboard.middlewares.ApiAuthMiddleware"), "DomainService", lambda: service
    )
    app = FastAPI()
    app.include_router(AppRouter.api)
    endpoints = {
        api.receive_dokploy_notification,
        api.get_dokploy_webhook_health,
        api.configure_dokploy_webhook,
        api.disable_dokploy_webhook,
        api.request_dokploy_webhook_secret_input,
    }
    for route in app.routes:
        if getattr(route, "endpoint", None) in endpoints:
            for dependency in route.dependant.dependencies:
                if dependency.name == "service":
                    app.dependency_overrides[dependency.call] = lambda: service
    app.add_middleware(ApiAuthMiddleware, routes=AppRouter.api.routes)
    with TestClient(app) as client:
        path = config["receiver_path"]
        assert client.post(path, content=BODY).status_code == 404
        assert client.post(path, content=BODY, headers={"Authorization": "Bearer wrong"}).status_code == 404
        assert client.post("/apps/dokploy/notifications/unknown", content=BODY).status_code == 404
        headers = {"Authorization": "Bearer receiver-token"}
        result = client.post(path, content=BODY, headers=headers)
        assert result.status_code == 200 and result.headers["Cache-Control"] == "no-store"
        assert client.post(path, content=BODY, headers=headers).json()["duplicate"]
        assert client.post(path, content=b" " * 65537, headers=headers).status_code == 413
        assert client.post(path, content=b"{}", headers=headers).status_code == 400
        from langboard_shared.core.security import AuthSecurity
        from langboard_shared.Env import Env

        access, refresh = AuthSecurity.authenticate(setup[1][1].id)
        platform_headers = {"Authorization": "Bearer " + access}
        client.cookies.set(Env.REFRESH_TOKEN_NAME, refresh)
        assert client.post(path, content=BODY, headers=platform_headers).status_code == 404
        base = f"/board/{setup[1][2].get_uid()}/settings/apps/dokploy/connections/{configured[1]['connection_uid']}"
        assert client.get(base + "/webhook-health").status_code == 401
        current = client.get(base + "/webhook-health", headers=platform_headers)
        assert current.status_code == 200 and current.json()["last_received_at"] == result.json()["received_at"]
        form = {
            "expected_revision": configured[1]["revision"],
            "expected_binding_revision": config["binding_revision"],
            "expected_config_revision": 1,
        }
        assert (
            client.post(
                base + "/webhook-disable", headers=platform_headers, json={**form, "expected_config_revision": 0}
            ).status_code
            == 409
        )
        assert (
            client.post(
                base + "/webhook-config",
                headers=platform_headers,
                json={**form, "credential_reference": configured[2]["uri"], "secret": "forbidden"},
            ).status_code
            == 400
        )
        input_path = f"/board/{setup[1][2].get_uid()}/settings/apps/dokploy/webhook-secret-input"
        assert client.post(input_path, headers=platform_headers).json()["state"] == "pending"
        assert client.post(base + "/webhook-disable", headers=platform_headers, json=form).status_code == 200
        assert client.post(path, content=BODY, headers=headers).status_code == 404
        with DbSession.use(readonly=False) as db:
            setup[1][4].actions = ["read"]
            db.update(setup[1][4])
        assert client.get(base + "/webhook-health", headers=platform_headers).status_code == 404


def test_migration_sqlite_unique_and_downgrade_preserves_receipts():
    from pathlib import Path
    import sqlalchemy as sa
    from alembic.migration import MigrationContext
    from alembic.operations import Operations

    path = Path(__file__).parents[2] / "langboard/migrations/versions/20261009003000-6b87540d97c2.py"
    spec = importlib.util.spec_from_file_location("webhook_migration", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.down_revision == "5a76439c86b1"
    engine = sa.create_engine("sqlite://")
    with engine.begin() as conn:
        module.op = Operations(MigrationContext.configure(conn))
        conn.execute(sa.text("CREATE TABLE board_app_binding (id BIGINT PRIMARY KEY)"))
        conn.execute(sa.text("CREATE TABLE app_connection (id BIGINT PRIMARY KEY)"))
        module.upgrade()
        payload = dict(
            id=1,
            created_at="2026-10-09",
            updated_at="2026-10-09",
            config_id=1,
            config_revision=1,
            payload_digest="a" * 64,
            received_at="2026-10-09T00:00:00Z",
            notification_type="build",
            status="success",
        )
        table = sa.Table("dokploy_notification_receipt", sa.MetaData(), autoload_with=conn)
        conn.execute(
            table.insert().values(
                **{
                    **payload,
                    "created_at": __import__("datetime").datetime.now(),
                    "updated_at": __import__("datetime").datetime.now(),
                }
            )
        )
        duplicate = {
            **payload,
            "id": 2,
            "created_at": __import__("datetime").datetime.now(),
            "updated_at": __import__("datetime").datetime.now(),
        }
        with pytest.raises(sa.exc.IntegrityError):
            conn.execute(table.insert().values(**duplicate))
        with pytest.raises(RuntimeError):
            module.downgrade()
        assert conn.execute(sa.select(table.c.id)).all() == [(1,)]
        conn.execute(table.delete())
        module.downgrade()


def test_receipt_insert_rollback_and_stream_revision_fence(configured, monkeypatch):
    original_insert = DbSession.insert

    def fail(db, record, *args, **kwargs):
        result = original_insert(db, record, *args, **kwargs)
        if isinstance(record, DokployNotificationReceipt):
            raise RuntimeError("Receipt transaction failure")
        return result

    monkeypatch.setattr(DbSession, "insert", fail)
    with pytest.raises(RuntimeError):
        accept(configured)
    with DbSession.use(readonly=False) as db:
        assert not db.exec(SqlBuilder.select.table(DokployNotificationReceipt)).all()
    monkeypatch.setattr(DbSession, "insert", original_insert)
    service, board, *_ = configured[0]
    config = configured[3]
    revision = webhook.authenticate(service, config["config_uid"], "Bearer receiver-token")
    with DbSession.use(readonly=False) as db:
        current = db.exec(SqlBuilder.select.table(DokployWebhookBinding)).first()
        current.config_revision += 1
        db.update(current)
    with pytest.raises(dk.DokployUnavailable):
        webhook.receive(service, config["config_uid"], "Bearer receiver-token", BODY, revision)
    with DbSession.use(readonly=False) as db:
        assert not db.exec(SqlBuilder.select.table(DokployNotificationReceipt)).all()


@pytest.mark.parametrize("status", ["success", "error"])
def test_official_generic_build_fields_discarded(configured, status):
    payload = {
        "title": "Build Success" if status == "success" else "Build Error",
        "message": "Build completed successfully" if status == "success" else "Build failed with errors",
        "projectName": "private",
        "applicationName": "private",
        "applicationType": "application",
        "buildLink": "https://private.invalid/build",
        "timestamp": "2026-10-09T00:00:00Z",
        "date": "private date",
        "status": status,
        "type": "build",
    }
    payload["domains" if status == "success" else "errorMessage"] = "private"
    result = accept(configured, json.dumps(payload).encode())
    assert "private" not in json.dumps(result)
    with DbSession.use(readonly=False) as db:
        receipt = db.exec(SqlBuilder.select.table(DokployNotificationReceipt)).first()
        assert receipt.status == status and "private" not in json.dumps(receipt.model_dump(), default=str)


def test_connected_without_selection_truthful_unconfigured(setup):
    service, board, *_ = setup
    conn = connect(setup)
    result = webhook.health(service, board[1], board[2].get_uid(), conn["connection_uid"])
    assert result["state"] == "unconfigured" and result["last_received_at"] is None
    assert result["binding_revision"] is None and result["resources"] == []


def test_receiver_binding_audit_rolls_back_failed_reconfiguration(configured, monkeypatch):
    setup, conn, reference, config = configured
    service, board, management, *_ = setup
    receiver_events = service.secret_reference.list_audit(board[1], reference["uri"])["items"]
    assert receiver_events[0]["action"] == "bound"
    assert receiver_events[0]["reason_code"] == "reference_bound"
    management_bound = sum(
        x["action"] == "bound" for x in service.secret_reference.list_audit(board[1], management["uri"])["items"]
    )
    original = service.secret_reference.audit_binding

    def fail(*args, **kwargs):
        original(*args, **kwargs)
        raise RuntimeError("Binding receipt failure")

    monkeypatch.setattr(service.secret_reference, "audit_binding", fail)
    with pytest.raises(RuntimeError):
        webhook.configure(
            service,
            board[1],
            board[2].get_uid(),
            conn["connection_uid"],
            conn["revision"],
            config["binding_revision"],
            config["config_revision"],
            reference["uri"],
            "notification-next",
        )
    with DbSession.use(readonly=False) as db:
        row = db.exec(SqlBuilder.select.table(DokployWebhookBinding)).first()
        assert row.config_revision == config["config_revision"] and row.notification_id is None
    assert service.secret_reference.list_audit(board[1], reference["uri"])["items"] == receiver_events
    assert (
        sum(x["action"] == "bound" for x in service.secret_reference.list_audit(board[1], management["uri"])["items"])
        == management_bound
    )


@pytest.mark.parametrize("change", ["disabled", "capability"])
def test_app_registry_revocation_blocks_webhook_without_losing_receipts(configured, change):
    from langboard_shared.domain.models import AppDefinition

    first = accept(configured)
    actor = configured[0][1][1]
    with DbSession.atomic() as db:
        db.insert(AppDefinition(key="dokploy", approved_by=actor.id, is_enabled=change != "disabled",
                                declaration={"capabilities": [] if change == "capability" else ["signals.read"]}))
    with pytest.raises(dk.DokployUnavailable):
        accept(configured)
    with DbSession.use(readonly=False) as db:
        rows = db.exec(SqlBuilder.select.table(DokployNotificationReceipt)).all()
        assert len(rows) == 1 and rows[0].get_uid() == first["receipt_uid"]
