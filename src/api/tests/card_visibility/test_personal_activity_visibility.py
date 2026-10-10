"""Cross-board personal history must not retain revoked or hidden card references."""

from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import Mock
import pytest
from langboard.mcp_tools import ActivityMcp
from langboard.routes.activities import ActivityApi
from langboard_shared.core.db import DbSession
from langboard_shared.core.db.DbEngine import DbEngine
from langboard_shared.core.schema import TimeBasedPagination
from langboard_shared.core.security.CollaborationChannel import CollaborationChannel
from langboard_shared.core.types import SafeDateTime
from langboard_shared.domain.models import (
    Card,
    ProjectActivity,
    ProjectWiki,
    ProjectWikiActivity,
    ProjectWikiAssignedUser,
    UserActivity,
)
from langboard_shared.domain.models.ProjectActivity import ProjectActivityType
from langboard_shared.domain.services.factory.ActivityService import ActivityService
from langboard_shared.infrastructure.repositories.factory.ActivityRepository import ActivityRepository


@pytest.mark.parametrize("channel", list(CollaborationChannel))
def test_personal_sql_pages_counts_recheck_current_card_visibility(current_card, channel):
    user, project, own, card_service = current_card
    for model in (ProjectActivity, ProjectWiki, ProjectWikiActivity, ProjectWikiAssignedUser, UserActivity):
        model.__table__.create(DbEngine.get_main_engine())
    now = SafeDateTime.now()
    with DbSession.use(readonly=False) as db:
        shared = Card(project_id=project.id, title="Shared", visibility="SHARED")
        internal = Card(project_id=project.id, title="Internal", visibility="INTERNAL")
        foreign = Card(project_id=project.id, title="Foreign", visibility="PRIVATE", owner_user_id=user.id+1, created_by_user_id=user.id+1)
        for card in (shared, internal, foreign):
            db.insert(card)
        for created in (now - timedelta(seconds=1), now + timedelta(seconds=1)):
            for card in (shared, own, internal, foreign):
                event = ProjectActivity(project_id=project.id, card_id=card.id, user_id=user.id,
                    created_at=created, activity_type=ProjectActivityType.CardUpdated)
                db.insert(event)
                db.insert(UserActivity(user_id=user.id, created_at=created, refer_activity_table="project_activity", refer_activity_id=event.id))
    repo = ActivityRepository(None, None)
    contexts = card_service.resolve_work_visibility_contexts(user, channel)
    expected = 2 if channel in (CollaborationChannel.HumanUI, CollaborationChannel.Mcp) else 1
    for page in range(1, expected+1):
        records, count = repo.get_list_by_user(user, TimeBasedPagination(limit=1, page=page, refer_time=now), contexts=contexts)
        assert len(records) == 1 and count == expected
    assert repo.get_list_by_user(user, TimeBasedPagination(limit=1, page=expected+1, refer_time=now), contexts=contexts)[0] == []
    assert repo.get_list_by_user(user, TimeBasedPagination(refer_time=now), only_count=True, contexts=contexts) == expected
    with DbSession.use(readonly=False) as db:
        shared.visibility = "INTERNAL"
        db.update(shared)
    assert repo.get_list_by_user(user, TimeBasedPagination(refer_time=now), only_count=True, contexts=contexts) == expected-1
    service = ActivityService(lambda _: card_service, lambda _: None, SimpleNamespace(activity=repo))
    with DbSession.use(readonly=False) as db:
        user.activated_at = None
        db.update(user)
    assert service.get_api_list_by_user(user, TimeBasedPagination(), channel=channel) is None
    assert service.get_api_list_by_user(user, TimeBasedPagination(), only_count=True, channel=channel) == 0


@pytest.mark.parametrize("channel", (CollaborationChannel.HumanUI, CollaborationChannel.Mcp))
def test_shared_user_history_does_not_expose_foreign_vault_detail(current_card, channel):
    user, project, own, card_service = current_card
    for model in (ProjectActivity, ProjectWiki, ProjectWikiActivity, ProjectWikiAssignedUser, UserActivity):
        model.__table__.create(DbEngine.get_main_engine())
    # Shared history keeps its existing mutual membership policy.
    from langboard_shared.domain.models import ProjectAssignedUser
    with DbSession.use(readonly=False) as db:
        db.insert(ProjectAssignedUser(project_id=project.id, user_id=user.id))
        foreign = Card(project_id=project.id, title="SECRET", visibility="PRIVATE", owner_user_id=user.id+1, created_by_user_id=user.id+1)
        db.insert(foreign)
        event = ProjectActivity(project_id=project.id, card_id=foreign.id, user_id=user.id,
                                activity_type=ProjectActivityType.CardUpdated, activity_history={"SECRET": "hidden"})
        db.insert(event)
    service = ActivityService(lambda _: card_service, lambda _: None, SimpleNamespace(activity=ActivityRepository(None, None)))
    for detail in (None, event.get_uid()):
        result = service.get_shared_user_activities(user, user.get_uid(), TimeBasedPagination(limit=1),
            activity_uid=detail, scope="project" if detail else None, channel=channel)
        assert result["activities"] == [] and result["has_more"] is False


def test_personal_rest_and_mcp_forward_transport_channel():
    command = Mock(return_value=None)
    service = SimpleNamespace(activity=SimpleNamespace(get_api_list_by_user=command))
    actor = object()
    ActivityApi.get_current_user_activities(SimpleNamespace(scope={"collaboration_channel": CollaborationChannel.HumanUI}),
        SimpleNamespace(only_count=False), actor, service)
    assert command.call_args.kwargs == {"channel": CollaborationChannel.HumanUI}
    ActivityMcp.get_current_user_activities(actor, service)
    assert command.call_args.kwargs == {"channel": CollaborationChannel.Mcp}


def test_personal_wiki_reference_requires_current_public_owner_or_assignment(current_card):
    from langboard_shared.domain.models import ProjectAssignedUser, ProjectRole
    from langboard_shared.domain.models.ProjectWikiActivity import ProjectWikiActivityType

    user, project, _, card_service = current_card
    for model in (ProjectActivity, ProjectWiki, ProjectWikiActivity, ProjectWikiAssignedUser, UserActivity):
        model.__table__.create(DbEngine.get_main_engine())
    with DbSession.use(readonly=False) as db:
        project.owner_id = user.id + 1
        db.update(project)
        member = ProjectAssignedUser(project_id=project.id, user_id=user.id)
        db.insert(member)
        db.insert(ProjectRole(project_id=project.id, user_id=user.id, actions=["read"]))
        wiki = ProjectWiki(project_id=project.id, title="Private wiki", is_public=False)
        db.insert(wiki)
        event = ProjectWikiActivity(project_id=project.id, project_wiki_id=wiki.id,
                                    user_id=user.id, activity_type=ProjectWikiActivityType.WikiUpdated)
        db.insert(event)
        db.insert(UserActivity(user_id=user.id, refer_activity_table="project_wiki_activity", refer_activity_id=event.id))
    repo = ActivityRepository(None, None)
    contexts = card_service.resolve_work_visibility_contexts(user, CollaborationChannel.Mcp)
    pagination = TimeBasedPagination()
    def rows():
        return repo.get_list_by_user(user, pagination, contexts=contexts)[0]
    assert rows() == []
    with DbSession.use(readonly=False) as db:
        assigned = ProjectWikiAssignedUser(project_assigned_id=member.id, project_wiki_id=wiki.id, user_id=user.id)
        db.insert(assigned)
    assert len(rows()) == 1
    with DbSession.use(readonly=False) as db:
        db.delete(assigned)
        wiki.is_public = True
        db.update(wiki)
    assert len(rows()) == 1
    with DbSession.use(readonly=False) as db:
        wiki.deleted_at = SafeDateTime.now()
        db.update(wiki)
    assert rows() == []
