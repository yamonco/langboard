import os
from types import SimpleNamespace
from typing import Any
import pytest


os.environ.setdefault("PROJECT_NAME", "langboard")

from langboard.card_workspace.infrastructure.native import (  # noqa: E402
    MAX_NATIVE_SECTION_SOURCE,
    NativeCardWorkspaceAdapter,
)


class Card:
    """Minimal native card double."""

    project_id = 1
    project_column_id = 2

    @staticmethod
    def api_response() -> dict[str, Any]:
        return {"uid": "c1", "title": "Card", "description": "Description"}


def _service(people: list[dict[str, Any]] | None = None) -> tuple[Any, list[tuple[str, int, int | None]]]:
    calls: list[tuple[str, int, int | None]] = []
    project = SimpleNamespace(id=1)
    card = Card()
    column = SimpleNamespace(id=2, project_id=1, name="Backlog")

    def checklists(target: Any, limit: int, checkitems_limit: int) -> list[dict[str, Any]]:
        calls.append(("checklists", limit, checkitems_limit))
        return []

    def attachments(target: Any, limit: int) -> list[dict[str, Any]]:
        calls.append(("attachments", limit, None))
        return []

    def metadata(*args: Any, **kwargs: Any) -> dict[str, str]:
        calls.append(("metadata", kwargs["limit"], None))
        return {}

    service = SimpleNamespace(
        project=SimpleNamespace(get_by_id_like=lambda uid: project),
        project_column=SimpleNamespace(get_by_id_like=lambda uid: column),
        card=SimpleNamespace(
            get_by_id_like=lambda uid: card,
            get_api_assigned_user_list=lambda target, limit: people or [],
            get_api_bot_scope_list=lambda target_project, target_card, limit: [],
            get_api_bot_schedule_list=lambda target_project, target_card, limit: [],
        ),
        project_label=SimpleNamespace(get_api_list_by_card=lambda target, limit: []),
        card_relationship=SimpleNamespace(get_api_list_by_card=lambda target, limit: []),
        checklist=SimpleNamespace(get_api_list_by_card=checklists),
        card_attachment=SimpleNamespace(get_api_list_by_card=attachments),
        metadata=SimpleNamespace(get_all_as_api=metadata),
    )
    return service, calls


def test_native_source_fetches_optional_sections_lazily_with_hard_query_limits() -> None:
    """The adapter passes a sentinel hard limit into every potentially large native query."""

    service, calls = _service()
    adapter = NativeCardWorkspaceAdapter(object(), service)

    source = adapter.get_card_bundle_source(
        "p1",
        "c1",
        frozenset({"checklists", "attachments", "metadata"}),
    )

    assert source is not None
    expected_limit = MAX_NATIVE_SECTION_SOURCE + 1
    assert calls == [
        ("checklists", expected_limit, expected_limit),
        ("attachments", expected_limit, None),
        ("metadata", expected_limit, None),
    ]


def test_native_source_rejects_over_bound_people_before_projection() -> None:
    """A native section that exceeds the contract fails instead of entering the projection graph."""

    people = [{"uid": f"u{i}"} for i in range(MAX_NATIVE_SECTION_SOURCE + 1)]
    service, _ = _service(people)
    adapter = NativeCardWorkspaceAdapter(object(), service)

    with pytest.raises(ValueError, match="safe 100-item MCP source bound"):
        adapter.get_card_bundle_source("p1", "c1", frozenset({"people"}))
