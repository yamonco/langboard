"""Recent-card restoration must not disclose a vault or revoked membership."""

from types import SimpleNamespace
import pytest
from langboard_shared.core.db import DbSession, SqlBuilder
from langboard_shared.core.db.DbEngine import DbEngine
from langboard_shared.core.storage import FileModel
from langboard_shared.core.types import SafeDateTime
from langboard_shared.domain.models import (
    Card,
    CardAttachment,
    CardComment,
    CardRelationship,
    Checkitem,
    Checklist,
    GlobalCardRelationshipType,
    Project,
    ProjectAssignedUser,
    ProjectColumn,
    User,
    WorkflowStageDefinition,
)
from langboard_shared.domain.services.CardVisibilityPolicy import CollaborationChannel
from langboard_shared.domain.services.factory.CardAttachmentService import CardAttachmentService
from langboard_shared.domain.services.factory.CardService import CardService
from langboard_shared.infrastructure.repositories.factory.CardRelationshipRepository import CardRelationshipRepository
from langboard_shared.infrastructure.repositories.factory.CardRepository import CardRepository
from langboard_shared.infrastructure.repositories.factory.ChecklistRepository import ChecklistRepository
from langboard_shared.infrastructure.repositories.factory.ProjectAssignedUserRepository import (
    ProjectAssignedUserRepository,
)
from langboard_shared.infrastructure.repositories.factory.ProjectColumnRepository import ProjectColumnRepository
from sqlalchemy import create_engine


def test_recent_cards_revalidate_actor_and_filter_visibility_before_return(monkeypatch):
    engine = create_engine("sqlite://")
    for model in (User, Project, ProjectColumn, ProjectAssignedUser, Card, CardComment, CardAttachment, WorkflowStageDefinition, Checklist, Checkitem, CardRelationship, GlobalCardRelationshipType):
        model.__table__.create(engine)
    monkeypatch.setattr(DbEngine, "get_main_engine", lambda: engine)
    monkeypatch.setattr(DbEngine, "get_readonly_engine", lambda: engine)
    try:
        with DbSession.use(readonly=False) as db:
            users = [User(firstname="Fixture", lastname=str(i), email=f"u{i}@example.invalid",
                          password="test-only", activated_at=SafeDateTime.now()) for i in range(2)]
            for user in users:
                db.insert(user)
            owner, member = users
            project = Project(owner_id=owner.id, title="Scoped recent fixture")
            db.insert(project)
            column = ProjectColumn(project_id=project.id, name="Work")
            db.insert(column)
            db.insert(ProjectColumn(project_id=project.id, name="Archive", is_archive=True))
            assignment = ProjectAssignedUser(project_id=project.id, user_id=member.id)
            db.insert(assignment)
            cards = [Card(project_id=project.id, project_column_id=column.id, title=visibility,
                          visibility=visibility, owner_user_id=vault_owner,
                          created_by_user_id=vault_owner) for visibility, vault_owner in (
                              ("SHARED", None), ("INTERNAL", None),
                              ("PRIVATE", member.id), ("PRIVATE", owner.id))]
            for card in cards:
                db.insert(card)
                db.insert(Checklist(card_id=card.id, title="Scoped checklist"))
                db.insert(CardAttachment(card_id=card.id, user_id=owner.id,
                    filename="proof.pdf", file=FileModel(storage_type="test", storage_name="test", original_filename="proof.pdf", path="/tmp/fixture", filename="proof.pdf"),
                    document_text="SearchProof document"))
        with DbSession.use(readonly=False) as db:
            relation_type = GlobalCardRelationshipType(parent_name="Parent", child_name="Child")
            db.insert(relation_type)
            edges = []
            for left, right in ((0, 1), (0, 2), (0, 3), (2, 3)):
                edge = CardRelationship(card_id_parent=cards[left].id, card_id_child=cards[right].id, relationship_type_id=relation_type.id)
                db.insert(edge)
                edges.append(edge)
        repository = SimpleNamespace(
            card=CardRepository(lambda _: None, lambda _: None),
            project_assigned_user=ProjectAssignedUserRepository(lambda _: None, lambda _: None),
        )
        scim = SimpleNamespace(is_employee=lambda user: False)
        service = CardService(lambda _: scim, lambda _: None, repository)
        uids = [card.get_uid() for card in cards]
        for channel in CollaborationChannel:
            expected = {uids[0], uids[2]} if channel in (CollaborationChannel.HumanUI, CollaborationChannel.Mcp) else {uids[0]}
            assert set(service.get_existing_uids(project, uids, user=member, channel=channel)) == expected
            assert {card.get_uid() for card in service.get_visible_by_project(project, member, channel)} == expected
            found = service.search_context_by_project(project, "SearchProof", user=member, channel=channel)
            assert {row["uid"] for row in found} == expected
            assert all(row["document_matches"][0]["snippet"] == "SearchProof document" for row in found)
            _, context = service.resolve_visibility_context(project, member, channel)
            # Scope both keyset rows and total before LIMIT, not after pagination.
            rows = repository.card.get_page_by_project(project, 1, context=context)
            assert len(rows) == min(2, len(expected))
            assert all(card.get_uid() in expected for card, _ in rows)
            assert repository.card.count_by_project(project, context=context) == len(expected)
            collected = []
            before_time = before_card = None
            while True:
                batch = repository.card.get_page_by_project(project, 1, before_time, before_card, context=context)
                if not batch:
                    break
                current = batch[0][0]
                collected.append(current.get_uid())
                before_time, before_card = current.updated_at, current.id
            assert set(collected) == expected and len(collected) == len(expected)
            service.get_work_states = lambda cards, **kwargs: {card.id: {"scoped": kwargs["context"] == context} for card in cards}
            service._get_linked_resource_payloads = lambda *args, **kwargs: {}
            api_cards, total, cursor = service.get_api_page_by_project(project, 1, user_or_bot=member, channel=channel, include_closed=True)
            assert total == len(expected) and api_cards[0]["uid"] in expected
            assert api_cards[0]["work_state"] == {"scoped": True}
            assert (cursor is not None) == (len(expected) > 1)
            assert service.get_api_page_by_project(project, 1, user_or_bot=None, channel=channel) is None

            for candidate in cards:
                resolved_card = service.resolve_readable_card(project, candidate, member, channel)
                assert (resolved_card is not None) == (candidate.get_uid() in expected)
                if resolved_card is None:
                    assert service.get_details(project, candidate, member, channel=channel) is None
            assert service.resolve_readable_card(project.id + 1, cards[0], member, channel) is None
            visible_edges = CardRelationshipRepository(None, None).get_all_by_card(cards[0], context=context)
            assert [edge.id for edge, _ in visible_edges] == ([edges[0].id] if context.can_read_internal else [])
            assert CardRelationshipRepository(None, None).get_all_by_card(cards[2], context=context) == []
            cutoff = SafeDateTime.now()
            board_cards = repository.card.get_board_list(project, cutoff, context=context)
            assert {card.get_uid() for card, _ in board_cards} == expected
            visible_ids = {card.id for card, _ in board_cards}
            checklists = ChecklistRepository(None, None).get_all_by_project(project, context=context)
            assert {checklist.card_id for checklist in checklists} == visible_ids
            columns = ProjectColumnRepository(None, None)
            counts = columns.get_all_by_project(project, context=context)
            assert next(count for item, count in counts if item.id == column.id) == len(expected)
            assert columns.get_work_counts(project, context=context)[column.id] == {
                "open_count": len(expected), "incomplete_count": len(expected),
            }
            excerpts = repository.card.search_document_matches(project, [card.id for card in cards], "SearchProof", context=context)
            assert {cards[i].id for i, uid in enumerate(uids) if uid in expected} == set(excerpts)
            limited = repository.card.search_context_by_project(project, "SearchProof", limit=1, context=context)
            assert len(limited) == 1 and limited[0][0].get_uid() in expected
        # A cached SHARED object cannot bypass a committed visibility change.
        with DbSession.use(readonly=False) as db:
            changed = cards[0].model_copy(deep=True)
            changed.visibility = "INTERNAL"
            db.update(changed)
        assert cards[0].visibility == "SHARED"
        assert service.resolve_readable_card(project, cards[0], member, CollaborationChannel.Mcp) is None
        assert service.get_api_page_by_project(project, 1, user_or_bot=member, channel=CollaborationChannel.Mcp) is None
        with DbSession.use(readonly=False) as db:
            changed.visibility = "SHARED"
            db.update(changed)
        assert service.resolve_readable_card(project, cards[0], member, CollaborationChannel.Mcp) is not None
        attachment_service = CardAttachmentService(lambda _: None, lambda _: None, repository)
        with DbSession.use(readonly=False) as db:
            attachment = db.exec(SqlBuilder.select.table(CardAttachment).where(CardAttachment.card_id == cards[0].id)).first()
            deleted_attachment = attachment.model_copy(deep=True)
            deleted_attachment.deleted_at = SafeDateTime.now()
            db.update(deleted_attachment)
        assert attachment.deleted_at is None
        assert attachment_service.get_by_id_like(attachment, consistent=True) is None
        scim.is_employee = lambda user: True
        assert set(service.get_existing_uids(project, uids, user=member, channel=CollaborationChannel.Mcp)) == set(uids[:3])
        _, internal_context = service.resolve_visibility_context(project, member, CollaborationChannel.Mcp)
        assert [edge.id for edge, _ in CardRelationshipRepository(None, None).get_all_by_card(cards[0], limit=1, context=internal_context)] == [edges[0].id]
        scim.is_employee = lambda user: None
        assert service.get_existing_uids(project, uids, user=member) == [uids[0]]
        # The auth User remains active in memory after primary DB revocation.
        with DbSession.use(readonly=False) as db:
            inactive = member.model_copy(deep=True)
            inactive.activated_at = None
            db.update(inactive)
        assert member.activated_at is not None
        assert service.resolve_readable_card(project, cards[0], member, CollaborationChannel.Mcp) is None
        assert service.get_existing_uids(project, uids, user=member, channel=CollaborationChannel.Mcp) == []
        assert service.search_context_by_project(project, "SearchProof", user=member, channel=CollaborationChannel.Mcp) == []
        with DbSession.use(readonly=False) as db:
            inactive.activated_at = member.activated_at
            db.update(inactive)
        assert service.get_existing_uids(project, uids, user=member, channel=CollaborationChannel.Mcp)
        with DbSession.use(readonly=False) as db:
            db.delete(assignment)
        assert service.get_existing_uids(project, uids, user=member, channel=CollaborationChannel.Mcp) == []
        assert service.get_api_page_by_project(project, 1, user_or_bot=member, channel=CollaborationChannel.Mcp) is None
        assert set(service.get_existing_uids(project, uids, user=owner, channel=CollaborationChannel.HumanUI)) == {uids[0], uids[3]}
        with DbSession.use(readonly=False) as db:
            removed_project = project.model_copy(deep=True)
            removed_project.deleted_at = SafeDateTime.now()
            db.update(removed_project)
        assert project.deleted_at is None
        assert service.get_existing_uids(project, uids, user=owner, channel=CollaborationChannel.HumanUI) == []
        assert service.get_existing_uids(project, [], user=owner) == []
        with pytest.raises(ValueError, match="200"):
            service.get_existing_uids(project, [uids[0]] * 201, user=owner)
    finally:
        engine.dispose()
