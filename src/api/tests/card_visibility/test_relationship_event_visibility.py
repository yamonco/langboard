"""Relationship invalidation carries no edges; the receiver reads a scoped projection."""
from types import SimpleNamespace
import pytest
from langboard.routes.board.BoardCardApi import get_card_relationships
from langboard_shared.core.db import DbSession
from langboard_shared.core.db.DbEngine import DbEngine
from langboard_shared.core.security.CollaborationChannel import CollaborationChannel
from langboard_shared.domain.models import Card, CardRelationship, GlobalCardRelationshipType
from langboard_shared.domain.services.factory.CardRelationshipService import CardRelationshipService
from langboard_shared.infrastructure.repositories.factory.CardRelationshipRepository import CardRelationshipRepository
from langboard_shared.publishers import CardRelationshipPublisher
from starlette.requests import Request


@pytest.mark.parametrize("current_card", ["sqlite-http"], indirect=True)
def test_relationship_read_uses_current_edge_audience(current_card, monkeypatch):
    user, project, card, card_service = current_card
    for model in (GlobalCardRelationshipType, CardRelationship):
        model.__table__.create(DbEngine.get_main_engine())
    with DbSession.use(readonly=False) as db:
        card.visibility = "SHARED"
        card.owner_user_id = None
        db.update(card)
        visible = Card(project_id=project.id, title="Visible", visibility="SHARED", created_by_user_id=user.id)
        hidden = Card(project_id=project.id, title="Hidden", visibility="INTERNAL", created_by_user_id=user.id)
        db.insert(visible)
        db.insert(hidden)
        kind = GlobalCardRelationshipType(parent_name="Parent", child_name="Child")
        db.insert(kind)
        edge = CardRelationship(card_id_parent=card.id, card_id_child=visible.id, relationship_type_id=kind.id)
        db.insert(edge)
        db.insert(CardRelationship(card_id_parent=card.id, card_id_child=hidden.id, relationship_type_id=kind.id))
    relation_service = CardRelationshipService(lambda _: None, lambda _: None,
        SimpleNamespace(card_relationship=CardRelationshipRepository(None, None)))
    service = SimpleNamespace(card=card_service, card_relationship=relation_service)
    request = Request({"type": "http", "headers": [], "collaboration_channel": CollaborationChannel.HumanUI})
    response = get_card_relationships(project.get_uid(), card.get_uid(), request, user, service)
    import json
    assert [item["uid"] for item in json.loads(response.body)["relationships"]] == [edge.get_uid()]
    with DbSession.use(readonly=False) as db:
        visible.visibility = "INTERNAL"
        db.update(visible)
    response = get_card_relationships(project.get_uid(), card.get_uid(), request, user, service)
    assert json.loads(response.body) == {"relationships": []}
    queued = []
    monkeypatch.setattr(CardRelationshipPublisher, "put_dispather", lambda model, publish: queued.append((model, publish)))
    CardRelationshipPublisher.updated(project, card)
    assert queued[0][0] == {"card_uid": card.get_uid(), "relationships_invalidated": True, "relationships": []}
    assert queued[0][1].card_uids == [card.get_uid()]
