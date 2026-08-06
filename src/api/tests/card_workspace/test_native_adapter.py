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


def test_native_project_creation_uses_other_and_exact_default_columns(monkeypatch: pytest.MonkeyPatch) -> None:
    """The native project API, not Hermes, owns the standard board shape."""

    class Actor:
        pass

    actor = Actor()
    project = SimpleNamespace(
        id=1,
        title="Operations",
        project_type="Other",
        get_uid=lambda: "project-one",
    )
    created_columns: list[str] = []

    def create_column(target_actor: Any, target_project: Any, name: str) -> Any:
        assert target_actor is actor
        assert target_project is project
        created_columns.append(name)
        return SimpleNamespace(
            api_response=lambda: {
                "uid": f"column-{len(created_columns)}",
                "name": name,
                "order": len(created_columns) - 1,
            }
        )

    create_project_calls: list[tuple[Any, str, str | None, str]] = []
    service = SimpleNamespace(
        project=SimpleNamespace(
            create=lambda *args: (
                create_project_calls.append(args),
                project,
            )[1],
            delete=lambda *_args: pytest.fail("successful creation must not roll back"),
        ),
        project_column=SimpleNamespace(create=create_column),
    )
    monkeypatch.setattr("langboard.card_workspace.infrastructure.native.User", Actor)

    result = NativeCardWorkspaceAdapter(actor, service).create_project_board(
        "Operations",
        "Room board",
    )

    assert create_project_calls == [(actor, "Operations", "Room board", "Other")]
    assert created_columns == ["Backlog", "In Progress", "Done"]
    assert result["project"] == {
        "uid": "project-one",
        "title": "Operations",
        "project_type": "Other",
        "url": "http://localhost:5173/board/project-one",
    }
    assert [column["name"] for column in result["columns"]] == created_columns


def test_native_project_creation_rolls_back_partial_board(monkeypatch: pytest.MonkeyPatch) -> None:
    """A failed default-column creation cannot leave a partial native board."""

    class Actor:
        pass

    actor = Actor()
    project = SimpleNamespace(id=1)
    deleted: list[Any] = []
    attempts = 0

    def create_column(*_args: Any) -> Any:
        nonlocal attempts
        attempts += 1
        if attempts == 2:
            raise RuntimeError("column insert failed")
        return SimpleNamespace(api_response=lambda: {"uid": "backlog"})

    service = SimpleNamespace(
        project=SimpleNamespace(
            create=lambda *_args: project,
            delete=lambda target_actor, target_project: deleted.append((target_actor, target_project)),
        ),
        project_column=SimpleNamespace(create=create_column),
    )
    monkeypatch.setattr("langboard.card_workspace.infrastructure.native.User", Actor)

    with pytest.raises(RuntimeError, match="column insert failed"):
        NativeCardWorkspaceAdapter(actor, service).create_project_board("Operations", None)

    assert deleted == [(actor, project)]


def test_native_card_creation_selects_server_side_leftmost_active_column() -> None:
    """Callers cannot select a destination; archive and input order are ignored."""

    project = SimpleNamespace(id=1)
    created: list[tuple[Any, ...]] = []
    card = {"uid": "card-one", "title": "First task"}
    service = SimpleNamespace(
        project=SimpleNamespace(get_by_id_like=lambda _uid: project),
        project_column=SimpleNamespace(
            get_api_list_by_project=lambda _project: [
                {"uid": "done", "name": "Done", "order": 20, "is_archive": False},
                {"uid": "archive", "name": "Archive", "order": -1, "is_archive": True},
                {"uid": "backlog", "name": "Backlog", "order": 10, "is_archive": False},
            ]
        ),
        card=SimpleNamespace(create=lambda *args: (created.append(args), (object(), card))[1]),
    )

    result = NativeCardWorkspaceAdapter(object(), service).create_card_in_leftmost_column(
        "project-one",
        "First task",
        None,
        None,
    )

    assert created[0][2] == "backlog"
    assert result == {
        "card": card,
        "column": {"uid": "backlog", "name": "Backlog"},
    }
