"""Raw attachment URLs must enforce the same current card audience."""
import os
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import uuid4
import pytest
from langboard.routes.file import FileApi
from langboard_shared.core.routing import ApiException
from langboard_shared.domain.models import User


@pytest.mark.parametrize("denial", ["anonymous", "orphan", "hidden", "role", "revoked", "replaced"])
def test_raw_attachment_url_never_returns_hidden_bytes(monkeypatch, denial):
    actor = User(firstname="Fixture", lastname="User", email="fixture@example.invalid", password="test-only")
    request = SimpleNamespace(scope={})
    attachment = SimpleNamespace(id=7, card_id=11, file=object())
    owner = Mock(return_value=None if denial == "orphan" else attachment)
    resolver = Mock(return_value=None if denial == "hidden" else (object(), SimpleNamespace(is_linked_resource=False), object()))
    service = SimpleNamespace(card_attachment=SimpleNamespace(resolve_file_owner=owner), card=SimpleNamespace(resolve_readable_card=resolver), project=SimpleNamespace(get_user_role_actions_by_project=lambda *_: [] if denial == "role" else ["*"]))
    monkeypatch.setattr(FileApi.MiddlewareHelper, "validate_auth", lambda scope: 401 if denial == "anonymous" else actor)
    monkeypatch.setattr(FileApi.BaseStorage, "decrypt_storage_type", lambda _: "local")
    def download(*args):
        args[-1].write(b"secret")
        if denial == "revoked":
            resolver.return_value = None
        elif denial == "replaced":
            owner.return_value = SimpleNamespace(id=8, card_id=11, file=object())
        return True
    reader = Mock(side_effect=download)
    monkeypatch.setattr(FileApi.Storage, "download", reader)
    with pytest.raises(ApiException.NotFound_404):
        FileApi.get_file(request, "encrypted", "card_attachment", "proof.pdf", service)
    if denial not in {"revoked", "replaced"}:
        reader.assert_not_called()


@pytest.mark.parametrize("namespace", ["avatar", "bot_avatar", "card_attachment"])
def test_public_avatar_and_authorized_attachment_streams_preserve_bytes(monkeypatch, namespace):
    actor = User(firstname="Fixture", lastname="User", email="fixture@example.invalid", password="test-only")
    attachment = SimpleNamespace(id=7, card_id=11, file=object())
    service = SimpleNamespace(card_attachment=SimpleNamespace(resolve_file_owner=lambda *_: attachment), card=SimpleNamespace(resolve_readable_card=lambda *_: (object(), SimpleNamespace(is_linked_resource=False), object())), project=SimpleNamespace(get_user_role_actions_by_project=lambda *_: ["*"]))
    auth = Mock(return_value=actor)
    monkeypatch.setattr(FileApi.MiddlewareHelper, "validate_auth", auth)
    monkeypatch.setattr(FileApi.BaseStorage, "decrypt_storage_type", lambda _: "local")
    def download(*args):
        args[-1].write(b"authorized")
        return True
    monkeypatch.setattr(FileApi.Storage, "download", download)
    response = FileApi.get_file(SimpleNamespace(scope={}), "encrypted", namespace, "proof.pdf", service)
    assert response.media_type == "application/pdf"
    file = response.background.args[0] if response.background.args else response.background.func.__self__
    assert file.read() == b"authorized"
    file.close()
    if namespace == "card_attachment":
        assert response.headers["cache-control"] == "private, no-store"
    else:
        auth.assert_not_called()


@pytest.mark.parametrize(("namespace", "filename"), [("../card_attachment", "file"), ("avatar", "../card_attachment/file"), ("avatar", "..\\file"), ("avatar", "..")])
def test_raw_url_path_aliases_are_rejected_before_storage(monkeypatch, namespace, filename):
    reader = Mock()
    monkeypatch.setattr(FileApi.Storage, "download", reader)
    with pytest.raises(ApiException.NotFound_404):
        FileApi.get_file(SimpleNamespace(scope={}), "encrypted", namespace, filename, object())
    reader.assert_not_called()


@pytest.mark.parametrize("database_url", [
    "sqlite://",
    pytest.param(
        os.environ.get("LANGBOARD_FILE_TEST_DATABASE_URL", "postgresql+psycopg://"),
        marks=pytest.mark.skipif(
            not os.environ.get("LANGBOARD_FILE_TEST_DATABASE_URL"),
            reason="Set LANGBOARD_FILE_TEST_DATABASE_URL to a disposable PostgreSQL database",
        ),
    ),
])
def test_file_provenance_uses_exact_live_database_object_not_cached_rows(monkeypatch, database_url):
    from langboard_shared.core.db import DbSession
    from langboard_shared.core.db.DbEngine import DbEngine
    from langboard_shared.core.storage import FileModel
    from langboard_shared.core.types import SafeDateTime
    from langboard_shared.domain.models import CardAttachment
    from langboard_shared.domain.services.factory.CardAttachmentService import CardAttachmentService
    from sqlalchemy import create_engine, text
    schema = "file_provenance_" + uuid4().hex
    engine = create_engine(database_url)
    if engine.dialect.name == "postgresql":
        with engine.begin() as db:
            db.execute(text(f'CREATE SCHEMA "{schema}"'))
        engine.dispose()
        engine = create_engine(database_url, connect_args={"options": f"-csearch_path={schema}"})
        with engine.begin() as db:
            db.execute(text('CREATE TABLE "user" (id BIGINT PRIMARY KEY)'))
            db.execute(text('CREATE TABLE card (id BIGINT PRIMARY KEY)'))
            db.execute(text('INSERT INTO "user" VALUES (1)'))
            db.execute(text('INSERT INTO card VALUES (2)'))
    CardAttachment.__table__.create(engine)
    monkeypatch.setattr(DbEngine, "get_main_engine", lambda: engine)
    monkeypatch.setattr(DbEngine, "get_readonly_engine", lambda: engine)
    service = CardAttachmentService(lambda _: None, lambda _: None, SimpleNamespace())
    def attachment(backend="local", namespace="card_attachment", filename="proof.pdf"):
        return CardAttachment(user_id=1, card_id=2, filename=filename, file=FileModel(storage_type=backend, storage_name=namespace, filename=filename, original_filename=filename, path="/fixture"))
    try:
        source = attachment()
        foreign = attachment("s3")
        with DbSession.use(readonly=False) as db:
            db.insert(source)
            db.insert(foreign)
        assert service.resolve_file_owner("local", "card_attachment", "proof.pdf").id == source.id
        assert service.resolve_file_owner("s3", "card_attachment", "proof.pdf").id == foreign.id
        assert service.resolve_file_owner("local", "avatar", "proof.pdf") is None
        assert service.resolve_file_owner("local", "card_attachment", "missing.pdf") is None
        duplicate = attachment()
        with DbSession.use(readonly=False) as db:
            db.insert(duplicate)
        assert service.resolve_file_owner("local", "card_attachment", "proof.pdf") is None
        with DbSession.use(readonly=False) as db:
            duplicate.deleted_at = SafeDateTime.now()
            db.update(duplicate)
        assert service.resolve_file_owner("local", "card_attachment", "proof.pdf").id == source.id
        with DbSession.use(readonly=False) as db:
            deleted = source.model_copy(deep=True)
            deleted.deleted_at = SafeDateTime.now()
            db.update(deleted)
        assert source.deleted_at is None
        assert service.resolve_file_owner("local", "card_attachment", "proof.pdf") is None
    finally:
        if engine.dialect.name == "postgresql":
            with engine.begin() as db:
                db.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        engine.dispose()
