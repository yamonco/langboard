import os
from importlib import import_module
from types import SimpleNamespace
from typing import Any
import pytest


os.environ.setdefault("PROJECT_NAME", "langboard")

from langboard_shared.core.types import SafeDateTime  # noqa: E402
from langboard_shared.domain.services.factory.CardService import CardService  # noqa: E402


card_service_module = import_module("langboard_shared.domain.services.factory.CardService")


class FakeCard:
    def __init__(self, card_id: int, uid: str, archived_at: SafeDateTime | None = None) -> None:
        self.id = card_id
        self._uid = uid
        self.archived_at = archived_at
        self.is_linked_resource = False

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
        project_wiki=SimpleNamespace(get_headers_by_project_and_uids=lambda _project, _uids: []),
        project_wiki_assigned_user=SimpleNamespace(
            get_assigned_wiki_ids=lambda _user, _wiki_ids: set(),
        ),
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
