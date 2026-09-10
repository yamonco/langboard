import os
from contextlib import contextmanager
from datetime import timedelta
from importlib import import_module
from types import SimpleNamespace
from typing import Any
import pytest
import sqlalchemy as sa
from pydantic import SecretStr
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool


os.environ.setdefault("PROJECT_NAME", "langboard")

from langboard.routes.board.BoardApi import get_project_cards  # noqa: E402
from langboard_shared.core.db import DbSession, EditorContentModel  # noqa: E402
from langboard_shared.core.types import SafeDateTime  # noqa: E402
from langboard_shared.domain.models import (  # noqa: E402
    Card,
    CardAssignedProjectLabel,
    CardAssignedUser,
    CardComment,
    CardRelationship,
    Checklist,
    GlobalCardRelationshipType,
    Project,
    ProjectAssignedUser,
    ProjectColumn,
    ProjectLabel,
    User,
)
from langboard_shared.domain.services.factory.CardService import CardService  # noqa: E402
from langboard_shared.infrastructure.repositories.factory.CardAssignedUserRepository import (  # noqa: E402
    CardAssignedUserRepository,
)
from langboard_shared.infrastructure.repositories.factory.CardRelationshipRepository import (  # noqa: E402
    CardRelationshipRepository,
)
from langboard_shared.infrastructure.repositories.factory.CardRepository import CardRepository  # noqa: E402
from langboard_shared.infrastructure.repositories.factory.ChecklistRepository import ChecklistRepository  # noqa: E402
from langboard_shared.infrastructure.repositories.factory.ProjectLabelRepository import (  # noqa: E402
    ProjectLabelRepository,
)


card_service_module = import_module("langboard_shared.domain.services.factory.CardService")


class FakeCard:
    is_linked_resource = False

    def __init__(self, card_id: int, uid: str, archived_at: SafeDateTime | None = None) -> None:
        self.id = card_id
        self._uid = uid
        self.archived_at = archived_at

    def get_uid(self) -> str:
        return self._uid

    def api_response(self) -> dict[str, Any]:
        return {"uid": self._uid, "archived_at": self.archived_at}

    def board_api_response(self, **values: Any) -> dict[str, Any]:
        return {"uid": self._uid, **values}


def _service(card_repository: Any, calls: dict[str, Any] | None = None) -> CardService:
    calls = calls if calls is not None else {}

    def capture(name: str):
        def inner(_project: Any, archive_visible_since: SafeDateTime) -> list[Any]:
            calls[name] = archive_visible_since
            return []

        return inner

    repository = SimpleNamespace(
        card=card_repository,
        card_assigned_user=SimpleNamespace(get_all_by_project=capture("members")),
        card_relationship=SimpleNamespace(get_all_by_project=capture("relationships")),
        project_label=SimpleNamespace(get_all_card_labels_by_project=capture("labels")),
    )
    return CardService(lambda _service: None, lambda _name: None, repository)


def test_board_list_passes_one_visibility_cutoff_to_all_hot_path_queries(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = SimpleNamespace(id=1, archive_visible_days=7)
    card = FakeCard(10, "visible-card")
    observed: dict[str, Any] = {}

    def get_board_list(_project: Any, cutoff: SafeDateTime) -> list[tuple[FakeCard, int]]:
        observed["cutoff"] = cutoff
        return [(card, 2)]

    monkeypatch.setattr(card_service_module.InfraHelper, "get_by_id_like", lambda _model, value: project)
    before = SafeDateTime.now()
    result = _service(SimpleNamespace(get_board_list=get_board_list), observed).get_board_list(project)
    after = SafeDateTime.now()

    assert before.timestamp() - 7 * 86400 <= observed["cutoff"].timestamp() <= after.timestamp() - 7 * 86400
    assert observed["members"] == observed["cutoff"]
    assert observed["relationships"] == observed["cutoff"]
    assert observed["labels"] == observed["cutoff"]
    assert result == [
        {
            "uid": "visible-card",
            "count_comment": 2,
            "member_uids": [],
            "relationships": [],
            "labels": [],
        }
    ]


def test_board_route_passes_one_request_cutoff_to_cards_and_checklists(monkeypatch: pytest.MonkeyPatch) -> None:
    now = SafeDateTime.fromisoformat("2026-09-10T12:00:00+00:00")
    project = SimpleNamespace(archive_visible_days=7)
    calls: dict[str, SafeDateTime] = {}
    monkeypatch.setattr(SafeDateTime, "now", lambda: now)
    service = SimpleNamespace(
        project=SimpleNamespace(get_by_id_like=lambda _uid: project),
        app_setting=SimpleNamespace(get_api_global_relationship_list=lambda: []),
        project_column=SimpleNamespace(
            get_api_list_by_project=lambda _project: [],
            get_api_bot_scopes_by_project=lambda _project: [],
            get_api_bot_schedule_list_by_project=lambda _project: [],
        ),
        card=SimpleNamespace(
            get_board_list=lambda _project, _actor, cutoff: (calls.__setitem__("cards", cutoff), [])[1],
        ),
        checklist=SimpleNamespace(
            get_api_list_only_by_project=lambda _project, *, archive_visible_since: (
                calls.__setitem__("checklists", archive_visible_since),
                [],
            )[1],
        ),
    )

    get_project_cards("project", service=service)

    expected = now - timedelta(days=7)
    assert calls == {"cards": expected, "checklists": expected}


def test_archive_page_uses_archive_order_cursor_and_search_count(monkeypatch: pytest.MonkeyPatch) -> None:
    project = SimpleNamespace(id=1)
    archived_at = SafeDateTime.fromisoformat("2026-09-10T12:30:00+00:00")
    card = FakeCard(10, "archived-card", archived_at)
    column = SimpleNamespace(name="Archive")
    calls: list[tuple[Any, ...]] = []
    card_repository = SimpleNamespace(
        get_archived_page_by_project=lambda *args: (calls.append(args), [(card, column), (card, column)])[1],
        count_archived_by_project=lambda *args: (calls.append(args), 9)[1],
    )
    monkeypatch.setattr(card_service_module.InfraHelper, "get_by_id_like", lambda _model, value: project)

    result = _service(card_repository).get_api_archived_page_by_project(project, 1, input_value="decision")

    assert result == (
        [{"uid": "archived-card", "archived_at": archived_at, "project_column_name": "Archive"}],
        9,
        (archived_at.isoformat(), "archived-card"),
    )
    assert calls[0] == (project, 1, None, None, "decision")
    assert calls[1] == (project, "decision")


def test_hot_queries_share_the_exact_boundary_and_hide_cold_relationship_endpoints(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Real SQL reads agree at the cutoff, including an edge with one cold endpoint."""

    engine = sa.create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    tables = [
        User.__table__,
        Project.__table__,
        ProjectColumn.__table__,
        Card.__table__,
        CardComment.__table__,
        ProjectAssignedUser.__table__,
        CardAssignedUser.__table__,
        GlobalCardRelationshipType.__table__,
        CardRelationship.__table__,
        ProjectLabel.__table__,
        CardAssignedProjectLabel.__table__,
        Checklist.__table__,
    ]
    User.metadata.create_all(engine, tables=tables)
    cutoff = SafeDateTime.fromisoformat("2026-09-10T12:00:00+00:00")
    active_id, boundary_id, cold_id = 101, 102, 103

    with engine.begin() as connection:
        connection.execute(
            User.__table__.insert(),
            {
                "id": 1,
                "firstname": "Test",
                "lastname": "User",
                "email": "test@example.invalid",
                "username": "test-user",
                "password": SecretStr("unused"),
                "is_admin": False,
                "preferred_lang": "en-US",
            },
        )
        connection.execute(
            Project.__table__.insert(),
            {
                "id": 1,
                "owner_id": 1,
                "title": "Boundary project",
                "project_type": "Other",
                "archive_visible_days": 7,
            },
        )
        connection.execute(
            ProjectColumn.__table__.insert(),
            {"id": 10, "project_id": 1, "name": "Work", "order": 0, "is_archive": False},
        )
        connection.execute(
            Card.__table__.insert(),
            [
                {
                    "id": active_id,
                    "project_id": 1,
                    "project_column_id": 10,
                    "title": "Active",
                    "description": EditorContentModel(content=""),
                    "order": 0,
                    "archived_at": None,
                },
                {
                    "id": boundary_id,
                    "project_id": 1,
                    "project_column_id": 10,
                    "title": "Boundary",
                    "description": EditorContentModel(content=""),
                    "order": 1,
                    "archived_at": cutoff,
                },
                {
                    "id": cold_id,
                    "project_id": 1,
                    "project_column_id": 10,
                    "title": "Cold",
                    "description": EditorContentModel(content=""),
                    "order": 2,
                    "archived_at": cutoff - timedelta(microseconds=1),
                },
            ],
        )
        connection.execute(
            ProjectAssignedUser.__table__.insert(),
            {"id": 20, "project_id": 1, "user_id": 1, "starred": False},
        )
        connection.execute(
            CardAssignedUser.__table__.insert(),
            [
                {"id": 201 + offset, "project_assigned_id": 20, "card_id": card_id, "user_id": 1}
                for offset, card_id in enumerate((active_id, boundary_id, cold_id))
            ],
        )
        connection.execute(
            GlobalCardRelationshipType.__table__.insert(),
            {"id": 30, "parent_name": "Parent", "child_name": "Child", "description": "Hierarchy"},
        )
        connection.execute(
            CardRelationship.__table__.insert(),
            [
                {"id": 301, "relationship_type_id": 30, "card_id_parent": active_id, "card_id_child": boundary_id},
                {"id": 302, "relationship_type_id": 30, "card_id_parent": active_id, "card_id_child": cold_id},
            ],
        )
        connection.execute(
            ProjectLabel.__table__.insert(),
            {"id": 40, "project_id": 1, "name": "Label", "color": "blue", "description": "", "order": 0},
        )
        connection.execute(
            CardAssignedProjectLabel.__table__.insert(),
            [
                {"id": 401 + offset, "card_id": card_id, "project_label_id": 40}
                for offset, card_id in enumerate((active_id, boundary_id, cold_id))
            ],
        )
        connection.execute(
            Checklist.__table__.insert(),
            [
                {"id": 501 + offset, "card_id": card_id, "title": "Checklist", "order": 0, "is_checked": False}
                for offset, card_id in enumerate((active_id, boundary_id, cold_id))
            ],
        )

    @contextmanager
    def use_database(*, readonly: bool):
        with Session(engine, expire_on_commit=False) as session:
            yield DbSession(session, readonly=readonly)

    monkeypatch.setattr(DbSession, "use", use_database)

    def make_repo(repository: Any) -> Any:
        return repository(lambda _type: None, lambda _name: None)

    project = 1

    cards = make_repo(CardRepository).get_board_list(project, cutoff)
    members = make_repo(CardAssignedUserRepository).get_all_by_project(project, cutoff)
    relationships = make_repo(CardRelationshipRepository).get_all_by_project(project, cutoff)
    labels = make_repo(ProjectLabelRepository).get_all_card_labels_by_project(project, cutoff)
    checklists = make_repo(ChecklistRepository).get_all_by_project(project, cutoff)

    assert {card.id for card, _ in cards} == {active_id, boundary_id}
    assert {assignment.card_id for _, assignment in members} == {active_id, boundary_id}
    assert {relationship.id for relationship, _ in relationships} == {301}
    assert {assignment.card_id for _, assignment in labels} == {active_id, boundary_id}
    assert {checklist.card_id for checklist in checklists} == {active_id, boundary_id}
