import os
from types import SimpleNamespace
from unittest.mock import Mock
import pytest


os.environ.setdefault("PROJECT_NAME", "langboard")
from langboard.mcp_tools import CardMcp


def fixture(monkeypatch):
    card = SimpleNamespace(id=7, is_linked_resource=False)
    attachment = SimpleNamespace(card_id=7, deleted_at=None, filename="report.pdf", file=object())
    document = {
        "generation": "current",
        "status": "indexed",
        "content_hash": "hash",
        "content": {"markdown": "한글 日本語 中文 " * 1000},
        "embedding_config": {"api_key": "must-not-return"},
    }
    service = SimpleNamespace(
        card=SimpleNamespace(resolve_readable_card=Mock(return_value=(object(), card, object()))),
        project=SimpleNamespace(get_user_role_actions_by_project=Mock(return_value=["*"])),
        card_attachment=SimpleNamespace(get_by_id_like=Mock(return_value=attachment)),
        docling_metadata=SimpleNamespace(get_document_by_attachment_uid=Mock(return_value=document)),
    )
    monkeypatch.setattr(CardMcp, "_get_card_in_project", lambda *_: (object(), card))
    return service, card, attachment, document


@pytest.mark.parametrize("denial", ["revoked", "foreign", "deleted", "linked"])
def test_denied_or_deleted_sources_never_load_transcription(monkeypatch, denial):
    service, card, attachment, _ = fixture(monkeypatch)
    if denial == "revoked":
        service.project.get_user_role_actions_by_project.return_value = []
    if denial == "foreign":
        attachment.card_id = 99
    if denial == "deleted":
        attachment.deleted_at = "deleted"
    if denial == "linked":
        card.is_linked_resource = True
    with pytest.raises(ValueError, match="unavailable"):
        CardMcp.read_card_document("board", "card", "attachment", object(), service)
    service.docling_metadata.get_document_by_attachment_uid.assert_not_called()


def test_read_is_bounded_non_destructive_and_generation_fenced(monkeypatch):
    service, _, _, document = fixture(monkeypatch)
    result = CardMcp.read_card_document("board", "card", "attachment", object(), service, max_chars=128)
    assert result["content"] == document["content"]["markdown"][:128]
    assert result["next_offset"] == 128 and result["content_hash"] == "hash"
    assert "embedding_config" not in result
    second = CardMcp.read_card_document(
        "board",
        "card",
        "attachment",
        object(),
        service,
        offset=128,
        max_chars=128,
        expected_generation=result["generation"],
    )
    assert second["content"] == document["content"]["markdown"][128:256]
    document["generation"] = "replaced"
    with pytest.raises(ValueError, match="generation changed"):
        CardMcp.read_card_document("board", "card", "attachment", object(), service, expected_generation="current")
    assert document["content"]["markdown"] == "한글 日本語 中文 " * 1000


@pytest.mark.parametrize("offset,max_chars", [(-1, 128), (False, 128), (0, 8001), (0, False)])
def test_invalid_bounds_never_load_sources(monkeypatch, offset, max_chars):
    service, _, _, _ = fixture(monkeypatch)
    with pytest.raises(ValueError):
        CardMcp.read_card_document("board", "card", "attachment", object(), service, offset=offset, max_chars=max_chars)
    service.card_attachment.get_by_id_like.assert_not_called()


def test_pending_document_does_not_expose_stale_content(monkeypatch):
    service, _, _, document = fixture(monkeypatch)
    document["status"] = "pending"
    result = CardMcp.read_card_document("board", "card", "attachment", object(), service)
    assert result["content"] == "" and result["next_offset"] is None


@pytest.mark.parametrize("changed", ["permission", "generation", "pointer", "embedding_config", "deleted", "binding_deleted", "binding_disabled", "binding_type", "binding_endpoint", "unchanged"])
def test_vector_search_rechecks_current_source_after_provider_call(monkeypatch, changed):
    from contextlib import nullcontext
    from langboard_shared.domain.models.InternalBot import InternalBotType
    from langboard_shared.tasks.docling import DocumentEmbedding as embedding
    from langboard_shared.tasks.docling import DocumentSqliteStore as sqlite_module
    from langboard_shared.tasks.docling import DocumentVectorQuery as query_module
    from langboard_shared.tasks.docling.DocumentRetrievalSettings import DocumentRetrievalSettings
    from langboard_shared.tasks.docling.DocumentVectorGeneration import embedding_fingerprint

    service, card, attachment, document = fixture(monkeypatch)
    config = {"base_url": "https://fixture.invalid", "model_name": "fixture"}
    fingerprint = embedding_fingerprint(
        provider=config["base_url"], model=config["model_name"], dimensions=3, version="v1"
    )
    document["embedding_config"] = {"binding_uid": "binding"}
    document["embedding"] = {
        "source_generation": "current",
        "pointer": {
            "board_uid": "board",
            "card_uid": "card",
            "attachment_uid": "attachment",
            "content_hash": "hash",
            "embedding_fingerprint": fingerprint,
            "chunk_ids": ["chunk"],
            "storage": {"type": "sqlite"},
        },
    }
    service.internal_bot = SimpleNamespace(
        get_current_by_id_like=Mock(return_value=SimpleNamespace(value="binding", bot_type=InternalBotType.DocumentEmbedding))
    )
    monkeypatch.setattr(
        embedding,
        "validate_embedding_config",
        lambda value: (config, DocumentRetrievalSettings(enabled=value != "disabled", dimensions=3)),
    )
    def resolve(_snapshot, value):
        if value == "endpoint_changed":
            raise ValueError("Embedding endpoint changed")
        return "private"
    monkeypatch.setattr(embedding, "resolve_embedding_snapshot", resolve)
    monkeypatch.setattr(embedding, "create_document_embeddings", lambda *_: object())
    monkeypatch.setattr(sqlite_module, "open_sqlite_vector_store", lambda *_, **kw: nullcontext(object()))

    class ExistingPath:
        def __truediv__(self, other):
            return self

        def is_file(self):
            return True

    monkeypatch.setattr(CardMcp, "Env", SimpleNamespace(DATA_DIR=ExistingPath(), get_from_env=lambda *_: ""))

    def revoke(*args, **kwargs):
        if changed == "permission":
            service.project.get_user_role_actions_by_project.return_value = []
        elif changed == "deleted":
            attachment.deleted_at = "deleted"
        elif changed == "binding_deleted":
            service.internal_bot.get_current_by_id_like.return_value = None
        elif changed == "binding_type":
            service.internal_bot.get_current_by_id_like.return_value.bot_type = InternalBotType.ProjectChat
        elif changed in {"binding_disabled", "binding_endpoint"}:
            service.internal_bot.get_current_by_id_like.return_value.value = (
                "disabled" if changed == "binding_disabled" else "endpoint_changed"
            )
        elif changed != "unchanged":
            latest = {**document, "embedding": {**document["embedding"]}}
            if changed == "generation":
                latest["generation"] = "replacement"
            elif changed == "embedding_config":
                latest["embedding_config"] = {"binding_uid": "replacement"}
            else:
                latest["embedding"]["pointer"] = {**document["embedding"]["pointer"], "generation": "replacement"}
            service.docling_metadata.get_document_by_attachment_uid.return_value = latest
        return [{"content": "authorized excerpt", "pages": [3]}]

    monkeypatch.setattr(query_module, "search_vector_generation", revoke)
    if changed == "unchanged":
        result = CardMcp.search_card_document("board", "card", "attachment", "query", object(), service)
        assert result["matches"] == [{"content": "authorized excerpt", "pages": [3]}]
        assert result["generation"] == "current"
    else:
        with pytest.raises(ValueError, match="unavailable|generation changed"):
            CardMcp.search_card_document("board", "card", "attachment", "query", object(), service)


@pytest.mark.parametrize("phase", ["before", "during"])
def test_visibility_revocation_never_returns_transcription(monkeypatch, phase):
    service, _, _, document = fixture(monkeypatch)
    if phase == "before":
        service.card.resolve_readable_card.return_value = None
    else:
        def read(*args):
            service.card.resolve_readable_card.return_value = None
            return document
        service.docling_metadata.get_document_by_attachment_uid.side_effect = read
    with pytest.raises(ValueError, match="unavailable"):
        CardMcp.read_card_document("board", "card", "attachment", object(), service)
    if phase == "before":
        service.docling_metadata.get_document_by_attachment_uid.assert_not_called()


@pytest.fixture(params=["sqlite://", "postgresql-test"])
def binding_store(monkeypatch, request):
    from uuid import uuid4
    from langboard_shared.core.db.DbEngine import DbEngine
    from langboard_shared.domain.models import InternalBot
    from sqlalchemy import create_engine, text

    url = request.param
    if url == "postgresql-test":
        url = os.environ.get("LANGBOARD_FILE_TEST_DATABASE_URL")
        if not url:
            pytest.skip("Dedicated PostgreSQL proof URL not set")
    admin = create_engine(url)
    schema = None
    if admin.dialect.name == "postgresql":
        schema = f"document_binding_{uuid4().hex}"
        with admin.begin() as connection:
            connection.execute(text(f"CREATE SCHEMA {schema}"))
        engine = create_engine(url, connect_args={"options": f"-csearch_path={schema}"})
    else:
        engine = admin
    InternalBot.__table__.create(engine)
    monkeypatch.setattr(DbEngine, "get_main_engine", lambda: engine)

    def no_replica():
        pytest.fail("Document retrieval must read current binding from the primary")

    monkeypatch.setattr(DbEngine, "get_readonly_engine", no_replica)
    try:
        yield engine
    finally:
        engine.dispose()
        if schema:
            with admin.begin() as connection:
                connection.execute(text(f"DROP SCHEMA {schema} CASCADE"))
            admin.dispose()


@pytest.mark.parametrize("change", ["disabled", "deleted", "endpoint", "unchanged"])
def test_vector_return_uses_current_primary_binding(monkeypatch, binding_store, change):
    from contextlib import nullcontext
    from json import dumps
    from langboard_shared.core.db import DbSession
    from langboard_shared.domain.models import InternalBot
    from langboard_shared.domain.models.BaseBotModel import BotPlatform, BotPlatformRunningType
    from langboard_shared.domain.models.InternalBot import InternalBotType
    from langboard_shared.domain.services.factory.InternalBotService import InternalBotService
    from langboard_shared.tasks.docling import DocumentEmbedding as embedding
    from langboard_shared.tasks.docling import DocumentVectorQuery as query_module
    from langboard_shared.tasks.docling import DocumentVectorStore as vector_module
    from langboard_shared.tasks.docling.DocumentVectorGeneration import embedding_fingerprint

    config = {"agent_llm": "OpenAI Compatible", "base_url": "https://fixture.invalid/v1", "model_name": "fixture",
              "api_key": "test-only", "retrieval": {"enabled": True, "dimensions": 3}}
    with DbSession.use(readonly=False) as db:
        binding = InternalBot(bot_type=InternalBotType.DocumentEmbedding, display_name="Fixture",
                              platform=BotPlatform.Default, platform_running_type=BotPlatformRunningType.Default,
                              value=dumps(config))
        db.insert(binding)
    service, _card, _attachment, document = fixture(monkeypatch)
    service.internal_bot = InternalBotService(lambda _: None, lambda _: None, None)
    document["embedding_config"] = embedding.snapshot_embedding_config(binding.value, binding.get_uid())
    document["embedding"] = {"source_generation": "current", "pointer": {
        "board_uid": "board", "card_uid": "card", "attachment_uid": "attachment", "content_hash": "hash",
        "embedding_fingerprint": embedding_fingerprint(provider=config["base_url"], model="fixture", dimensions=3, version="v1"),
        "chunk_ids": ["chunk"], "storage": {"type": "sqlite"},
    }}
    monkeypatch.setattr(embedding, "create_document_embeddings", lambda *_: object())
    monkeypatch.setattr(vector_module, "open_document_vector_store", lambda *a, **kw: nullcontext(object()))

    def search(*args, **kwargs):
        if change != "unchanged":
            with DbSession.use(readonly=False) as db:
                if change == "deleted":
                    db.delete(binding)
                else:
                    if change == "disabled":
                        config["retrieval"]["enabled"] = False
                    else:
                        config["base_url"] = "https://other.invalid/v1"
                    binding.value = dumps(config)
                    db.update(binding)
        return [{"content": "authorized excerpt"}]

    monkeypatch.setattr(query_module, "search_vector_generation", search)
    if change == "unchanged":
        assert CardMcp.search_card_document("board", "card", "attachment", "query", object(), service)["matches"]
    else:
        with pytest.raises(ValueError, match="binding unavailable"):
            CardMcp.search_card_document("board", "card", "attachment", "query", object(), service)
    if change == "deleted":
        assert service.internal_bot.get_current_by_id_like(binding) is None


@pytest.mark.parametrize("status", ["pending", "failed"])
@pytest.mark.parametrize("revoke", [False, True])
def test_reindex_keeps_previous_model_searchable_with_current_acl(monkeypatch, tmp_path, status, revoke):
    from json import dumps, loads
    from langboard_shared.domain.models.InternalBot import InternalBotType
    from langboard_shared.tasks.docling import DocumentEmbedding as embedding
    from langboard_shared.tasks.docling import DocumentVectorQuery as query_module
    from langboard_shared.tasks.docling.DocumentRetrievalSettings import DocumentRetrievalSettings
    from langboard_shared.tasks.docling.DocumentSqliteStore import open_sqlite_vector_store
    from langboard_shared.tasks.docling.DocumentSqliteVectorStore_test import Fixture
    from langboard_shared.tasks.docling.DocumentVectorGeneration import embedding_fingerprint
    from langboard_shared.tasks.docling.DocumentVectorStore import stage_vector_generation

    service, _card, _attachment, document = fixture(monkeypatch)
    config = {
        "agent_llm": "OpenAI Compatible", "base_url": "https://fixture.invalid",
        "model_name": "previous-model", "retrieval": {"enabled": True, "dimensions": 3},
    }
    old_snapshot = embedding.snapshot_embedding_config(dumps(config), "binding")
    current_config = {**config, "model_name": "new-model"}
    document["embedding_config"] = embedding.snapshot_embedding_config(dumps(current_config), "binding")
    service.internal_bot = SimpleNamespace(get_current_by_id_like=Mock(return_value=SimpleNamespace(
        value=dumps(current_config), bot_type=InternalBotType.DocumentEmbedding,
    )))
    fingerprint = embedding_fingerprint(
        provider=config["base_url"], model=config["model_name"], dimensions=3, version="v1"
    )
    directory = tmp_path / "document-retrieval"
    directory.mkdir()
    with open_sqlite_vector_store(directory / (fingerprint + ".sqlite"), Fixture(), dimensions=3) as store:
        pointer = stage_vector_generation(
            store,
            source={"board_uid": "board", "card_uid": "card", "attachment_uid": "attachment",
                    "content_hash": "hash", "embedding_fingerprint": fingerprint},
            text="alpha previous searchable generation 한국어 日本語 中文",
            splitter=DocumentRetrievalSettings().splitter, storage={"type": "sqlite"},
        )
    document["embedding"] = {
        "status": status, "source_generation": "current", "pointer": pointer, "config": old_snapshot,
    }
    monkeypatch.setattr(CardMcp, "Env", SimpleNamespace(DATA_DIR=tmp_path, get_from_env=lambda *_: "https://fixture.invalid"))
    def create(value, allowed):
        assert loads(value)["model_name"] == "previous-model"
        assert config["base_url"] in allowed
        return Fixture()
    monkeypatch.setattr(embedding, "create_document_embeddings", create)
    real_search = query_module.search_vector_generation
    def search(*args, **kwargs):
        result = real_search(*args, **kwargs)
        if revoke:
            service.project.get_user_role_actions_by_project.return_value = []
        return result
    monkeypatch.setattr(query_module, "search_vector_generation", search)
    if revoke:
        with pytest.raises(ValueError, match="unavailable"):
            CardMcp.search_card_document("board", "card", "attachment", "alpha", object(), service)
    else:
        result = CardMcp.search_card_document("board", "card", "attachment", "alpha", object(), service)
        assert len(result["matches"]) == 1
        assert "previous searchable" in result["matches"][0]["content"]
        assert result["matches"][0]["source"]["embedding_fingerprint"] == fingerprint
        assert "embedding_config" not in result and "config" not in result
    assert document["embedding"]["pointer"] == pointer
    assert document["embedding_config"]["model_name"] == "new-model"
