"""Attachment generation fencing preserves prior searchable text and deleted sources."""

import os


os.environ.setdefault("PROJECT_NAME", "langboard")

from types import SimpleNamespace
from unittest.mock import Mock
from sqlalchemy import create_engine
from ....core.db import DbSession, SqlBuilder
from ....core.db.DbEngine import DbEngine
from ....core.storage import FileModel
from ....domain.models import Card, CardAttachment, CardDocumentArtifact, CardMetadata, Project, ProjectColumn, User
from ....domain.services import DomainService
from .InternalBotService import InternalBotService


def test_document_generation_fences_old_results_and_preserves_previous_text_on_failure(monkeypatch):
    engine = create_engine("sqlite://")
    for model in (User, Project, ProjectColumn, Card, CardAttachment, CardDocumentArtifact, CardMetadata):
        model.__table__.create(engine)
    monkeypatch.setattr(DbEngine, "get_main_engine", lambda: engine)
    monkeypatch.setattr(DbEngine, "get_readonly_engine", lambda: engine)
    with DbSession.use(readonly=False) as db:
        owner = User(firstname="Test", lastname="Owner", email="document@example.invalid", password="test-only")
        db.insert(owner)
        project = Project(owner_id=owner.id, title="Document fixture")
        db.insert(project)
        column = ProjectColumn(project_id=project.id, name="Todo")
        db.insert(column)
        card = Card(project_id=project.id, project_column_id=column.id, title="Document")
        db.insert(card)
        attachment = CardAttachment(
            user_id=owner.id,
            card_id=card.id,
            filename="report.pdf",
            file=FileModel(
                storage_type="test",
                storage_name="test",
                original_filename="report.pdf",
                filename="report.pdf",
                path="/fixture",
            ),
        )
        db.insert(attachment)
    service = DomainService()
    docling = service.docling_metadata
    other_project = Project(owner_id=owner.id, title="Foreign board")
    with DbSession.use(readonly=False) as db:
        db.insert(other_project)
    binding = Mock(side_effect=AssertionError("Foreign attachment must not resolve provider or enqueue"))
    original_get_service = service.card_attachment._get_service
    monkeypatch.setattr(
        service.card_attachment,
        "_get_service",
        lambda cls: SimpleNamespace(get_document_vision_binding=binding)
        if cls is InternalBotService
        else original_get_service(cls),
    )
    assert (
        service.card_attachment.request_document_processing(
            other_project.get_uid(), card.get_uid(), attachment.get_uid()
        )
        is None
    )
    binding.assert_not_called()
    assert service.card_attachment.request_document_processing(other_project, card, attachment) is None
    binding.assert_not_called()
    config = {"binding_uid": "provider", "model_name": "model"}
    assert docling.queue_document(CardMetadata, card, attachment.get_uid(), attachment.filename, vision_config=config)
    first = docling.get_document_by_attachment_uid(CardMetadata, card, attachment.get_uid())["generation"]
    assert not docling.queue_document(
        CardMetadata, card, attachment.get_uid(), attachment.filename, vision_config=config, force=True
    )
    assert docling.claim_document(CardMetadata, card, attachment.get_uid(), attachment.filename, generation=first)
    first = docling.get_document_by_attachment_uid(CardMetadata, card, attachment.get_uid())["generation"]
    assert docling.mark_document_indexed(
        CardMetadata,
        card,
        attachment.get_uid(),
        "pdf",
        content={"markdown": "이전 전사", "search_keywords": {"en": ["document search"], "ja": ["文書検索"]},
                 "docling_document": {"schema_name": "DoclingDocument", "pages": {"1": {}}}},
        generation=first,
    )
    with DbSession.use(readonly=True) as db:
        artifact = db.exec(SqlBuilder.select.table(CardDocumentArtifact)).first()
        assert artifact and '"pages"' in artifact.document_json
    assert "docling_document" not in docling.get_document_by_attachment_uid(
        CardMetadata, card, attachment.get_uid()
    )["content"]
    first_embedding = {"status": "indexed", "pointer": {"generation": "first-vector"}}
    embedding_snapshot = {"binding_uid": "embedding-provider", "model_name": "embedding-model"}
    assert docling.publish_document_embedding(
        card,
        attachment.get_uid(),
        first,
        None,
        first_embedding,
        expected_embedding={},
        embedding_config=embedding_snapshot,
    )
    assert (
        docling.get_document_by_attachment_uid(CardMetadata, card, attachment.get_uid())["embedding_config"]
        == embedding_snapshot
    )
    assert not docling.publish_document_embedding(
        card, attachment.get_uid(), first, None, {"status": "failed"}, expected_embedding={}
    )
    assert not docling.publish_document_embedding(
        card, attachment.get_uid(), first, "different-hash", {"status": "failed"}
    )
    assert (
        docling.get_document_by_attachment_uid(CardMetadata, card, attachment.get_uid())["embedding"] == first_embedding
    )
    assert docling.queue_document(
        CardMetadata, card, attachment.get_uid(), attachment.filename, vision_config=config, force=True
    )
    second = docling.get_document_by_attachment_uid(CardMetadata, card, attachment.get_uid())["generation"]
    assert second != first
    assert not docling.claim_document(CardMetadata, card, attachment.get_uid(), attachment.filename, generation=first)
    assert not docling.mark_document_processing(
        CardMetadata, card, attachment.get_uid(), attachment.filename, 1, 2, generation=first
    )
    assert not docling.mark_document_indexed(
        CardMetadata, card, attachment.get_uid(), "pdf", content={"markdown": "오래된 결과"}, generation=first
    )
    assert docling.mark_document_failed(
        CardMetadata, card, attachment.get_uid(), attachment.filename, "failed", generation=second
    )
    with DbSession.use(readonly=True) as db:
        current = db.exec(SqlBuilder.select.table(CardAttachment).where(CardAttachment.id == attachment.id)).first()
    with DbSession.use(readonly=True) as db:
        preserved = db.exec(SqlBuilder.select.table(CardDocumentArtifact)).first()
        assert preserved.document_json == artifact.document_json
    assert current.document_text == "이전 전사\n\ndocument search 文書検索"
    assert (
        docling.get_document_by_attachment_uid(CardMetadata, card, attachment.get_uid())["content"]["markdown"]
        == "이전 전사"
    )
    docling.delete_document_by_attachment_uid(CardMetadata, card, attachment.get_uid())
    assert not docling.mark_document_failed(
        CardMetadata, card, attachment.get_uid(), attachment.filename, "late failure", generation=second
    )
    assert docling.get_document_by_attachment_uid(CardMetadata, card, attachment.get_uid()) is None
    service.close()
    engine.dispose()


def test_progress_publish_reads_primary_when_replica_is_unavailable(monkeypatch):
    from ....core.routing import SocketTopic
    from ....publishers import MetadataPublisher
    from .DoclingMetadataService import DOCLING_DOCUMENTS_METADATA_KEY

    engine = create_engine("sqlite://")
    CardMetadata.__table__.create(engine)
    monkeypatch.setattr(DbEngine, "get_main_engine", lambda: engine)

    def lagging_replica():
        raise AssertionError("Post-write publication must not read the replica")

    monkeypatch.setattr(DbEngine, "get_readonly_engine", lagging_replica)
    card = Card(id=123, project_id=1, project_column_id=2, title="Primary publication")
    value = '[{"attachment_uid":"source","status":"indexed","progress_percent":100}]'
    with DbSession.use(readonly=False) as db:
        db.insert(CardMetadata(card_id=card.id, key=DOCLING_DOCUMENTS_METADATA_KEY, value=value))
    publish = Mock()
    monkeypatch.setattr(MetadataPublisher, "updated_metadata", publish)
    service = DomainService()
    try:
        assert service.docling_metadata.load_documents(CardMetadata, card)[0]["status"] == "indexed"
        service.docling_metadata.publish_update(CardMetadata, card, SocketTopic.BoardCard)
        publish.assert_called_once_with(SocketTopic.BoardCard, card.get_uid(), DOCLING_DOCUMENTS_METADATA_KEY, value)
    finally:
        service.close()
        engine.dispose()
