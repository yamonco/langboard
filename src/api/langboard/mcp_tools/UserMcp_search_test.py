"""Validate explicit search periods before invoking the native query."""

import os
from types import SimpleNamespace
import pytest


os.environ.setdefault("PROJECT_NAME", "langboard")

from langboard.mcp_tools import UserMcp  # noqa: E402


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
    ) == {"cards": []}
    project, query, filters = calls[0]
    assert (project, query) == ("project", "release")
    assert filters["date_field"] == "created_at"
    assert filters["since"].isoformat() == "2026-09-15T00:00:00+09:00"
    assert filters["until"].isoformat() == "2026-09-16T00:00:00+09:00"


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
