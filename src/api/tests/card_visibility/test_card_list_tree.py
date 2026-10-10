from types import SimpleNamespace
from langboard.card_workspace.infrastructure.native import NativeCardWorkspaceAdapter
from langboard_shared.core.db import DbSession
from langboard_shared.core.db.DbEngine import DbEngine
from langboard_shared.domain.models import Card, CardRelationship, GlobalCardRelationshipType


def test_page_relationships_revalidate_both_endpoints_and_never_scan_other_pages(current_card):
    actor, project, anchor, card_service = current_card
    for model in (GlobalCardRelationshipType, CardRelationship):
        model.__table__.create(DbEngine.get_main_engine())
    with DbSession.use(readonly=False) as db:
        kind = GlobalCardRelationshipType(parent_name="Contains", child_name="Member", machine_semantic="contains")
        db.insert(kind)
        visible = Card(project_id=project.id, title="Readable", visibility="SHARED")
        hidden = Card(project_id=project.id, title="Never expose", visibility="PRIVATE", owner_user_id=actor.id + 1, created_by_user_id=actor.id + 1)
        outside = Card(project_id=project.id, title="Other page", visibility="SHARED")
        deleted = Card(project_id=project.id, title="Deleted", visibility="SHARED", deleted_at=anchor.created_at)
        for card in (visible, hidden, outside, deleted):
            db.insert(card)
            db.insert(CardRelationship(card_id_parent=anchor.id, card_id_child=card.id, relationship_type_id=kind.id))
    adapter = NativeCardWorkspaceAdapter(actor, SimpleNamespace(card=card_service))
    page = [c.get_uid() for c in (anchor, visible, hidden, deleted)]
    edges = adapter.get_project_card_relationships(project.get_uid(), page)
    assert len(edges) == 1
    assert edges[0]["child_card_uid"] == visible.get_uid()
    assert edges[0]["machine_semantic"] == "contains"
    with DbSession.use(readonly=False) as db:
        visible.visibility, visible.owner_user_id = "PRIVATE", actor.id + 1
        visible.created_by_user_id = actor.id + 1
        db.update(visible)
    assert adapter.get_project_card_relationships(project.get_uid(), page) == []
    assert adapter.get_project_card_relationships(project.get_uid(), []) == []
