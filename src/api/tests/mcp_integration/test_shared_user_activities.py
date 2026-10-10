"""Prove shared-history authorization before pagination against a real SQL engine."""

from datetime import timedelta
from types import SimpleNamespace
import pytest
from langboard_shared.core.db import DbSession
from langboard_shared.core.db.DbEngine import DbEngine
from langboard_shared.core.schema import TimeBasedPagination
from langboard_shared.domain.models import (
    Bot,
    Card,
    Project,
    ProjectActivity,
    ProjectAssignedUser,
    ProjectColumn,
    ProjectRole,
    ProjectWiki,
    ProjectWikiActivity,
    ProjectWikiAssignedUser,
    User,
)
from langboard_shared.domain.models.ProjectActivity import ProjectActivityType
from langboard_shared.domain.models.ProjectWikiActivity import ProjectWikiActivityType
from langboard_shared.domain.services.factory.ActivityService import ActivityService
from langboard_shared.infrastructure.repositories.factory.ActivityRepository import ActivityRepository
from sqlalchemy import create_engine, event


def test_shared_history_filters_before_paging_and_reauthorizes_detail(monkeypatch: pytest.MonkeyPatch) -> None:
    engine = create_engine("sqlite://")
    for model in (
        User,
        Bot,
        Project,
        ProjectAssignedUser,
        ProjectRole,
        ProjectColumn,
        Card,
        ProjectWiki,
        ProjectWikiAssignedUser,
        ProjectActivity,
        ProjectWikiActivity,
    ):
        model.__table__.create(engine)
    monkeypatch.setattr(DbEngine, "get_main_engine", lambda: engine)
    monkeypatch.setattr(DbEngine, "get_readonly_engine", lambda: engine)
    repository = ActivityRepository(lambda _: None, lambda _: None)
    service = ActivityService(lambda _: None, lambda _: None, SimpleNamespace(activity=repository))
    viewer = User(firstname="Viewer", lastname="Test", email="viewer@example.invalid", password="test")
    target = User(firstname="Target", lastname="Test", email="target@example.invalid", password="test")
    with DbSession.use(readonly=False) as db:
        db.insert(viewer)
        db.insert(target)
        shared = Project(owner_id=target.id, title="Shared board")
        private = Project(owner_id=target.id, title="Target only SECRET")
        db.insert(shared)
        db.insert(private)
        for project in (shared, private):
            db.insert(ProjectAssignedUser(project_id=project.id, user_id=target.id))
        member = ProjectAssignedUser(project_id=shared.id, user_id=viewer.id)
        db.insert(member)
        role = ProjectRole(project_id=shared.id, user_id=viewer.id, actions=["read"])
        db.insert(role)
        visible = ProjectActivity(
            project_id=shared.id,
            user_id=target.id,
            activity_type=ProjectActivityType.ProjectUpdated,
            activity_history={"before": "가" * 9000, "after": "나" * 9000},
        )
        hidden = ProjectActivity(
            project_id=private.id,
            user_id=target.id,
            activity_type=ProjectActivityType.ProjectUpdated,
            activity_history={"SECRET": "hidden"},
        )
        db.insert(visible)
        db.insert(hidden)
        wiki = ProjectWiki(project_id=shared.id, title="Private wiki SECRET", is_public=False)
        db.insert(wiki)
        wiki_event = ProjectWikiActivity(
            project_id=shared.id,
            project_wiki_id=wiki.id,
            user_id=target.id,
            activity_type=ProjectWikiActivityType.WikiUpdated,
            activity_history={"SECRET": "private wiki content"},
        )
        db.insert(wiki_event)
    statements = []
    event.listen(
        engine, "before_cursor_execute", lambda conn, cursor, sql, params, context, many: statements.append(sql)
    )
    pagination = TimeBasedPagination(limit=1)
    page = service.get_shared_user_activities(viewer, target.get_uid(), pagination)
    assert len(page["activities"]) == 1
    assert page["activities"][0]["project"]["title"] == "Shared board"
    assert not page["has_more"]
    assert "history" not in str(page) and "SECRET" not in str(page)
    assert "activity_history" not in next(sql for sql in statements if "UNION ALL" in sql)
    assert all(sql.lstrip().upper().startswith("SELECT") for sql in statements)
    start = (visible.created_at - timedelta(seconds=1)).isoformat()
    end = (visible.created_at + timedelta(seconds=1)).isoformat()
    assert (
        len(
            service.get_shared_user_activities(
                viewer, target.get_uid(), pagination, project_uid=shared.get_uid(), since=start, until=end
            )["activities"]
        )
        == 1
    )
    assert (
        service.get_shared_user_activities(viewer, target.get_uid(), pagination, project_uid=private.get_uid())[
            "activities"
        ]
        == []
    )
    assert service.get_shared_user_activities(viewer, target.get_uid(), pagination, until=start)["activities"] == []
    assert service.get_shared_user_activities(viewer, target.get_uid(), pagination, since=end)["activities"] == []
    assert (
        service.get_shared_user_activities(viewer, target.get_uid(), pagination, until=visible.created_at.isoformat())[
            "activities"
        ]
        == []
    )  # Exclusive end permits adjacent day windows without duplicates.
    for since, until in ((end, start), ("2026-09-15T00:00:00", None), ("not-a-date", None)):
        with pytest.raises(ValueError):
            service.get_shared_user_activities(viewer, target.get_uid(), pagination, since=since, until=until)
    detail = service.get_shared_user_activities(
        viewer, target.get_uid(), pagination, visible.get_uid(), "project", 0, 100
    )
    item = detail["activities"][0]
    assert len(item["history_fragment"]) == 100 and item["next_offset"] == 100
    next_item = service.get_shared_user_activities(
        viewer, target.get_uid(), pagination, visible.get_uid(), "project", 100, 100
    )["activities"][0]
    assert next_item["offset"] == 100
    assert (
        service.get_shared_user_activities(viewer, target.get_uid(), pagination, hidden.get_uid(), "project")[
            "activities"
        ]
        == []
    )
    assert (
        service.get_shared_user_activities(viewer, target.get_uid(), pagination, wiki_event.get_uid(), "wiki")[
            "activities"
        ]
        == []
    )
    with DbSession.use(readonly=False) as db:
        db.insert(ProjectWikiAssignedUser(project_assigned_id=member.id, user_id=viewer.id, project_wiki_id=wiki.id))
    mixed = service.get_shared_user_activities(viewer, target.get_uid(), TimeBasedPagination(limit=20))
    assert {item["activity_type"] for item in mixed["activities"]} == {"project_updated", "wiki_updated"}
    assert (
        len(
            service.get_shared_user_activities(viewer, target.get_uid(), pagination, wiki_event.get_uid(), "wiki")[
                "activities"
            ]
        )
        == 1
    )
    with DbSession.use(readonly=False) as db:
        role.actions = ["card_write"]
        db.update(role)
    assert (
        service.get_shared_user_activities(viewer, target.get_uid(), pagination, visible.get_uid(), "project")[
            "activities"
        ]
        == []
    )
    admin = SimpleNamespace(id=viewer.id, is_admin=True)
    assert repository.get_shared_user_activities(admin, target, pagination, hidden.get_uid(), "project") == []
    with pytest.raises(ValueError, match="scope"):
        service.get_shared_user_activities(viewer, target.get_uid(), pagination, visible.get_uid())
    with pytest.raises(ValueError, match="bounds"):
        service.get_shared_user_activities(viewer, target.get_uid(), pagination, offset=-1)
    engine.dispose()
