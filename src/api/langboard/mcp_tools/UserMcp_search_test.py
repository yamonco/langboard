"""Validate explicit search periods before invoking the native query."""

import os
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import Mock
import pytest


os.environ.setdefault("PROJECT_NAME", "langboard")

from langboard.mcp_tools import UserMcp  # noqa: E402
from langboard_shared.core.types import SnowflakeID  # noqa: E402
from langboard_shared.domain.services.factory.CardService import CardService  # noqa: E402


def test_search_passes_timezone_aware_half_open_period_to_native_query() -> None:
    calls = []
    service = SimpleNamespace(
        card=SimpleNamespace(
            search_context_by_project=lambda project, query, **filters: calls.append((project, query, filters)) or [],
        )
    )
    assert UserMcp.search_project_cards(
        "project",
        " release ",
        service,
        "created_at",
        "2026-09-15T00:00:00+09:00",
        "2026-09-16T00:00:00+09:00",
     user=SEARCH_USER) == {"cards": [], "workflow_stages": {}, "columns": {}}
    project, query, filters = calls[0]
    assert (project, query) == ("project", "release")
    assert filters["date_field"] == "created_at"
    assert filters["since"] == datetime.fromisoformat("2026-09-15T00:00:00+09:00")
    assert filters["until"] == datetime.fromisoformat("2026-09-16T00:00:00+09:00")


@pytest.mark.parametrize(
    ("since", "until"),
    [
        ("2026-09-15T00:00:00", None),
        ("not-a-date", None),
        ("2026-09-16T00:00:00Z", "2026-09-15T00:00:00Z"),
    ],
)
def test_search_rejects_invalid_period_before_service_access(since, until) -> None:
    with pytest.raises(ValueError):
        UserMcp.search_project_cards("project", "release", SimpleNamespace(), since=since, until=until, user=SEARCH_USER)


def test_my_work_scopes_projects_and_round_trips_keyset_cursor() -> None:
    project_uid = SnowflakeID(12).to_short_code()
    card_uid = SnowflakeID(34).to_short_code()
    page = Mock(return_value=([{"card_uid": card_uid}], ("2026-09-29T00:00:00+00:00", project_uid, card_uid)))
    service = SimpleNamespace(
        project=SimpleNamespace(
            get_api_list=lambda _: (
                [
                    {"uid": project_uid, "current_auth_role_actions": ["read"]},
                    {"uid": "hidden", "current_auth_role_actions": ["update"]},
                ],
                [],
            )
        ),
        card=SimpleNamespace(get_assigned_work_page=page),
    )
    user = SimpleNamespace(id=1)
    service.card._get_service = lambda _: service.project
    service.card.list_assigned_work = lambda *args, **kwargs: CardService.list_assigned_work(service.card, *args, **kwargs)
    first = UserMcp.list_my_work(user, service, limit=1)
    assert first["items"] == [{"card_uid": card_uid}]
    assert page.call_args.args[1:3] == ([project_uid], 1)
    UserMcp.list_my_work(user, service, cursor=first["next_cursor"], limit=1)
    assert page.call_args.args[3][1:] == (12, 34)
    with pytest.raises(ValueError, match="not readable"):
        UserMcp.list_my_work(user, service, project_uid="hidden")
    with pytest.raises(ValueError, match="Invalid My Work cursor"):
        UserMcp.list_my_work(user, service, cursor="bad!")


def test_search_resolves_distinct_workflow_once_and_keeps_bounded_description():
    state = {"workflow_stage": "released", "completed": True, "reasons": [{"code": "recorded", "message": "verbose"}]}
    cards = [
        {"uid": str(i), "description": {"content": "match"}, "project_column_uid": "c", "work_state": state}
        for i in range(3)
    ]
    resolve = Mock(
        return_value={
            "released": {
                "key": "released",
                "counts_as_completed": True,
                "entry_effects": ["stop_running_timers"],
                "translations": {"ko": {"name": "완료"}},
            }
        }
    )
    columns = Mock(return_value={})
    service = SimpleNamespace(
        card=SimpleNamespace(search_context_by_project=Mock(return_value=cards)),
        workflow_stage=SimpleNamespace(get_api_by_keys=resolve),
        project_column=SimpleNamespace(get_api_workflow_context=columns),
    )
    response = UserMcp.search_project_cards("p", "match", service, user=SEARCH_USER)
    resolve.assert_called_once_with({"released"})
    columns.assert_called_once_with("p", {"c"})
    assert service.card.search_context_by_project.call_args.kwargs["include_work_state"] is True
    assert response["workflow_stages"]["released"]["entry_effects"] == ["stop_running_timers"]
    assert "translations" not in response["workflow_stages"]["released"]
    assert all(
        item["description"] == {"content": "match"}
        and item["work_state"]["completed"] is True
        and "reasons" not in item["work_state"]
        for item in response["cards"]
    )


def test_document_search_tool_returns_sources_with_aggregate_excerpt_budget():
    cards = [
        {
            "uid": str(index),
            "title": "hit",
            "document_matches": [{"attachment_uid": "a", "filename": "report.pdf", "snippet": "한" * 2000}] * 4,
        }
        for index in range(20)
    ]
    service = SimpleNamespace(
        card=SimpleNamespace(search_context_by_project=lambda *args, **kwargs: cards),
        project_column=SimpleNamespace(get_api_workflow_context=lambda *args: {}),
    )
    response = UserMcp.search_project_cards("board", "한", service, user=SEARCH_USER)
    matches = [match for card in response["cards"] for match in card.get("document_matches", [])]
    assert sum(len(match["snippet"]) for match in matches) == 4000
    assert all(len(match["snippet"]) <= 500 and match["attachment_uid"] == "a" for match in matches)
    assert all(len(card.get("document_matches", [])) <= 2 for card in response["cards"])


SEARCH_USER = SimpleNamespace(id=1)
