"""Real storage/DB/native auth flow with an absent optional converter and captured delivery."""

import importlib
from importlib.util import find_spec
from json import dumps
from unittest.mock import Mock
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from langboard.middlewares.ApiAuthMiddleware import ApiAuthMiddleware
from langboard.middlewares.RoleMiddleware import RoleMiddleware
from langboard.routes.board import BoardCardAttachmentApi
from langboard_shared.core.broker import Broker
from langboard_shared.core.db import DbSession, SqlBuilder
from langboard_shared.core.db.DbEngine import DbEngine
from langboard_shared.core.routing import AppRouter
from langboard_shared.core.security import AuthSecurity
from langboard_shared.core.storage import Storage
from langboard_shared.core.storage.LocalStorage import LocalStorage
from langboard_shared.domain.models import Card, CardAttachment, CardMetadata, InternalBot
from langboard_shared.domain.models.BaseBotModel import BotPlatform, BotPlatformRunningType
from langboard_shared.domain.models.InternalBot import InternalBotType
from langboard_shared.domain.services import DomainService
from langboard_shared.domain.services.factory.DoclingMetadataService import DoclingMetadataService
from langboard_shared.domain.services.factory.WorkflowStageService_app_test import board  # noqa: F401, F811
from langboard_shared.Env import Env
from langboard_shared.publishers import CardAttachmentPublisher, CardPublisher
from langboard_shared.tasks.activities import CardAttachmentActivityTask
from langboard_shared.tasks.bots import CardAttachmentBotTask
from langboard_shared.tasks.docling import DoclingMetadataTask


@pytest.mark.parametrize("board", ["sqlite-http", "postgresql-test"], indirect=True)
def test_optional_converter_absence_preserves_http_upload_and_reports_worker_failure(board, monkeypatch, tmp_path):  # noqa: F811
    if find_spec("docling") is not None:
        pytest.skip("This integration gate requires an environment without document-processing installed")
    _, actor, project, _, _, columns, _ = board
    engine = DbEngine.get_main_engine()
    for model in (Card, CardAttachment, CardMetadata, InternalBot):
        model.__table__.create(engine)
    monkeypatch.setattr(DbEngine, "get_readonly_engine", DbEngine.get_main_engine)
    monkeypatch.setattr(type(Env), "LOCAL_STORAGE_DIR", property(lambda _: tmp_path))
    monkeypatch.setattr(Storage, "_storages", {"local": LocalStorage()})
    with DbSession.use(readonly=False) as db:
        card = Card(project_id=project.id, project_column_id=columns[0].id, title="Optional conversion")
        db.insert(card)
        binding = InternalBot(
            bot_type=InternalBotType.DocumentVision,
            display_name="Fixture vision",
            platform=BotPlatform.Default,
            platform_running_type=BotPlatformRunningType.Default,
            is_default=True,
            value=dumps(
                {"base_url": "https://provider.invalid/v1", "model_name": "vision", "document_processing_enabled": True}
            ),
        )
        db.insert(binding)
    service = DomainService()
    if engine.dialect.name == "sqlite":
        from itertools import count

        sequence = count(1)
        with engine.connect() as connection:
            connection.connection.driver_connection.create_function("nextval", 1, lambda _: next(sequence))
    else:
        from sqlalchemy import text

        with engine.begin() as db:
            db.execute(text("CREATE SEQUENCE content_change_seq"))
    monkeypatch.setattr(CardAttachmentPublisher, "uploaded", Mock())
    monkeypatch.setattr(CardPublisher, "metadata_changed", Mock())
    monkeypatch.setattr(CardAttachmentActivityTask, "card_attachment_uploaded", Mock())
    monkeypatch.setattr(CardAttachmentBotTask, "card_attachment_uploaded", Mock())
    monkeypatch.setattr(DoclingMetadataService, "publish_update", Mock())
    # Card visibility has dedicated tests; this gate isolates upload/conversion, not its ACL proof.
    monkeypatch.setattr(BoardCardAttachmentApi, "require_visible_card", lambda *args: card)
    delivered = []

    def send_task(name, *, args, kwargs):
        with DbSession.use(readonly=False) as db:
            assert db.exec(SqlBuilder.select.table(CardAttachment)).first() is not None
        delivered.append((name, args, kwargs))

    monkeypatch.setattr(Broker.celery, "send_task", send_task)
    monkeypatch.setattr(
        importlib.import_module("langboard.middlewares.ApiAuthMiddleware"), "DomainService", lambda: service
    )
    app = FastAPI()
    app.include_router(AppRouter.api)
    for route in app.routes:
        if getattr(route, "endpoint", None) is BoardCardAttachmentApi.upload_card_attachment:
            for dependency in route.dependant.dependencies:
                if dependency.name == "service":
                    app.dependency_overrides[dependency.call] = lambda: service
    app.add_middleware(RoleMiddleware, routes=AppRouter.api.routes)
    app.add_middleware(ApiAuthMiddleware, routes=AppRouter.api.routes)
    access, refresh = AuthSecurity.authenticate(actor.id)
    path = f"/board/{project.get_uid()}/card/{card.get_uid()}/attachment"
    payload = b"%PDF-1.4 optional-converter-fixture"
    with TestClient(app) as client:
        assert client.post(path, files={"attachment": ("report.pdf", payload)}).status_code == 401
        client.cookies.set(Env.REFRESH_TOKEN_NAME, refresh)
        response = client.post(
            path, files={"attachment": ("report.pdf", payload)}, headers={"Authorization": f"Bearer {access}"}
        )
        assert response.status_code == 201, response.text
    with DbSession.use(readonly=False) as db:
        attachment = db.exec(SqlBuilder.select.table(CardAttachment)).first()
    assert attachment is not None and Storage.get_file(attachment.file) == payload
    assert len(delivered) == 1 and delivered[0][0].endswith("index_card_attachment")
    document = service.docling_metadata.get_document_by_attachment_uid(CardMetadata, card, attachment.get_uid())
    assert document["status"] == "pending"
    download = Mock(side_effect=AssertionError("Missing optional converter must fail before file IO"))
    monkeypatch.setattr(DoclingMetadataTask.Storage, "download_file", download)
    DoclingMetadataTask._index_card_attachment(service, attachment, generation=document["generation"])
    failed = service.docling_metadata.get_document_by_attachment_uid(CardMetadata, card, attachment.get_uid())
    assert failed["status"] == "failed"
    assert "document-processing extra" in failed["error_message"]
    download.assert_not_called()
    assert Storage.get_file(attachment.file) == payload
    assert len(delivered) == 1
