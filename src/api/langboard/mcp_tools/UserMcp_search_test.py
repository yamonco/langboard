"""Validate explicit search periods before invoking the native query."""

import os
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import Mock
import pytest


os.environ.setdefault("PROJECT_NAME", "langboard")

from langboard.mcp_tools import UserMcp  # noqa: E402
from langboard_shared.core.types import SnowflakeID  # noqa: E402


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
    ) == {"cards": [], "workflow_stages": {}}
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
        UserMcp.search_project_cards("project", "release", SimpleNamespace(), since=since, until=until)


def test_my_work_scopes_projects_and_round_trips_keyset_cursor() -> None:
    project_uid = SnowflakeID(12).to_short_code()
    card_uid = SnowflakeID(34).to_short_code()
    page = Mock(return_value=([{"card_uid": card_uid}], ("2026-09-29T00:00:00+00:00", project_uid, card_uid)))
    service = SimpleNamespace(
        project=SimpleNamespace(get_api_list=lambda _: ([
            {"uid": project_uid, "current_auth_role_actions": ["read"]},
            {"uid": "hidden", "current_auth_role_actions": ["update"]},
        ], [])),
        card=SimpleNamespace(get_assigned_work_page=page),
    )
    user = SimpleNamespace(id=1)
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
    cards = [{"uid": str(i), "description": {"content": "match"}, "project_column_uid": "c", "work_state": state} for i in range(3)]
    resolve = Mock(return_value={"released": {"key": "released", "counts_as_completed": True, "entry_effects": ["stop_running_timers"], "translations": {"ko": {"name": "완료"}}}})
    service = SimpleNamespace(card=SimpleNamespace(search_context_by_project=Mock(return_value=cards)), workflow_stage=SimpleNamespace(get_api_by_keys=resolve))
    response = UserMcp.search_project_cards("p", "match", service)
    resolve.assert_called_once_with({"released"})
    assert service.card.search_context_by_project.call_args.kwargs["include_work_state"] is True
    assert response["workflow_stages"]["released"]["entry_effects"] == ["stop_running_timers"]
    assert "translations" not in response["workflow_stages"]["released"]
    assert all(item["description"] == {"content": "match"} and item["work_state"]["completed"] is True and "reasons" not in item["work_state"] for item in response["cards"])
