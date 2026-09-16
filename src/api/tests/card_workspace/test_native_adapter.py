import os
from types import SimpleNamespace
from typing import Any
from unittest.mock import Mock
import pytest


os.environ.setdefault("PROJECT_NAME", "langboard")

from langboard.card_workspace.domain import (  # noqa: E402
    CardDescriptionPatch,
    DescriptionPatchConflict,
    ExactTextReplacement,
    projection_revision,
)
from langboard.card_workspace.infrastructure.native import (  # noqa: E402
    MAX_NATIVE_SECTION_SOURCE,
    NativeCardWorkspaceAdapter,
)


class Card:
    """Minimal native card double."""

    project_id = 1
    project_column_id = 2
    created_by_user_id = None
    created_by_bot_id = None

    @staticmethod
    def api_response() -> dict[str, Any]:
        return {"uid": "c1", "title": "Card", "description": "Description"}


def test_project_identity_returns_real_guidance_without_inventing_legacy_descriptions() -> None:
    """Active destinations include their guidance; absent legacy guidance stays empty."""
    project = SimpleNamespace(get_uid=lambda: "p1", title="Workflow", project_type="Other")
    columns = [
        {"uid": "doing", "name": "Execution", "order": 2, "description": "Work has started"},
        {"uid": "ready", "name": "Queue", "order": 1},
        {"uid": "archive", "name": "Archive", "order": 0, "is_archive": True, "description": "Hidden"},
    ]
    service = SimpleNamespace(
        project=SimpleNamespace(get_by_id_like=lambda _: project),
        project_column=SimpleNamespace(get_api_list_by_project=lambda _: columns),
    )
    result = NativeCardWorkspaceAdapter(object(), service).get_project_identity("p1")
    assert result and result["columns"]["items"] == [
        {"uid": "ready", "name": "Queue", "order": 1, "description": ""},
        {"uid": "doing", "name": "Execution", "order": 2, "description": "Work has started"},
    ]


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
            can_delete=lambda actor, target: False,
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


@pytest.mark.parametrize(
    ("user_id", "bot_id", "service_name", "expected_type"),
    [(7, None, "user", "user"), (None, 9, "bot", "bot")],
)
def test_native_source_resolves_the_stored_creator_only(
    user_id: int | None,
    bot_id: int | None,
    service_name: str,
    expected_type: str,
) -> None:
    service, _ = _service()
    card = service.card.get_by_id_like("c1")
    card.created_by_user_id = user_id
    card.created_by_bot_id = bot_id
    calls: list[tuple[str, int]] = []

    def creator(actor_id: int) -> Any:
        calls.append((service_name, actor_id))
        return SimpleNamespace(api_response=lambda: {"uid": "creator", "type": expected_type})

    service.user = SimpleNamespace(get_by_id_like=creator if service_name == "user" else pytest.fail)
    service.bot = SimpleNamespace(get_by_id_like=creator if service_name == "bot" else pytest.fail)

    source = NativeCardWorkspaceAdapter(object(), service).get_card_bundle_source("p1", "c1", frozenset())

    assert source is not None
    assert source.details["creator"] == {"uid": "creator", "type": expected_type}
    assert calls == [(service_name, user_id if user_id is not None else bot_id)]


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


def test_native_checkitem_continuation_reads_only_the_requested_checklist() -> None:
    project = SimpleNamespace(id=1)
    card = SimpleNamespace(
        id=2,
        project_id=1,
        project_column_id=3,
        api_response=lambda: {"uid": "c1"},
    )
    column = SimpleNamespace(id=3, project_id=1, name="Backlog")
    checklist = SimpleNamespace(
        id=4,
        card_id=2,
        api_response=lambda: {"uid": "cl1", "title": "Checklist"},
    )
    calls: list[tuple[Any, Any, int]] = []
    service = SimpleNamespace(
        project=SimpleNamespace(get_by_id_like=lambda _uid: project),
        project_column=SimpleNamespace(get_by_id_like=lambda _uid: column),
        card=SimpleNamespace(get_by_id_like=lambda _uid: card),
        checklist=SimpleNamespace(
            get_by_id_like=lambda _uid: checklist,
            get_api_list_by_card=lambda *_args, **_kwargs: pytest.fail("bulk checklist query used"),
        ),
        checkitem=SimpleNamespace(
            get_api_list_by_checklist=lambda target_card, target_checklist, limit: (
                calls.append((target_card, target_checklist, limit)),
                [{"uid": "ci1", "title": "Item"}],
            )[1]
        ),
    )

    source = NativeCardWorkspaceAdapter(object(), service).get_card_bundle_source(
        "p1",
        "c1",
        frozenset({"checkitems:cl1"}),
    )

    assert source is not None
    assert source.checklists[0]["checkitems"] == [{"uid": "ci1", "title": "Item"}]
    assert calls == [(card, checklist, MAX_NATIVE_SECTION_SOURCE + 1)]


def test_native_project_identity_limits_the_column_query() -> None:
    project = SimpleNamespace(
        id=1,
        title="Delivery",
        project_type="Other",
        get_uid=lambda: "p1",
    )
    calls: list[int] = []
    service = SimpleNamespace(
        project=SimpleNamespace(get_by_id_like=lambda _uid: project),
        project_column=SimpleNamespace(
            get_api_list_by_project=lambda _project, limit: (
                calls.append(limit),
                [{"uid": "backlog", "name": "Backlog", "order": 0, "is_archive": False}],
            )[1]
        ),
    )

    result = NativeCardWorkspaceAdapter(object(), service).get_project_identity("p1")

    assert result is not None
    assert result["columns"]["items"] == [{"uid": "backlog", "name": "Backlog", "order": 0}]
    assert calls == [MAX_NATIVE_SECTION_SOURCE + 1]


def test_native_project_creation_uses_template_service(monkeypatch: pytest.MonkeyPatch) -> None:
    """The native project API owns template selection and board shape."""

    class Actor:
        pass

    actor = Actor()
    project = SimpleNamespace(
        id=1,
        title="Operations",
        project_type="Other",
        get_uid=lambda: "project-one",
    )
    names = ["Backlog", "Ready", "In Progress", "Review", "Done"]
    columns = [
        SimpleNamespace(
            api_response=lambda name=name, order=order: {"uid": f"column-{order}", "name": name, "order": order}
        )
        for order, name in enumerate(names)
    ]
    create_project_calls: list[tuple[Any, str, str | None, str, str | None]] = []
    service = SimpleNamespace(
        project_template=SimpleNamespace(
            create_project=lambda *args: (
                create_project_calls.append(args),
                (project, columns, SimpleNamespace(name="SI")),
            )[1],
        ),
    )
    monkeypatch.setattr("langboard.card_workspace.infrastructure.native.User", Actor)

    result = NativeCardWorkspaceAdapter(actor, service).create_project_board(
        "Operations",
        "Room board",
    )

    assert create_project_calls == [(actor, "Operations", "Room board", "Other", None, False)]
    assert result["project"] == {
        "uid": "project-one",
        "title": "Operations",
        "project_type": "Other",
        "url": "http://localhost:5173/board/project-one",
        "template": "SI",
    }
    assert [column["name"] for column in result["columns"]] == names


def test_native_project_creation_propagates_template_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    """The adapter does not hide atomic template creation failures."""

    class Actor:
        pass

    actor = Actor()
    service = SimpleNamespace(
        project_template=SimpleNamespace(
            create_project=lambda *_args: (_ for _ in ()).throw(RuntimeError("column insert failed"))
        )
    )
    monkeypatch.setattr("langboard.card_workspace.infrastructure.native.User", Actor)

    with pytest.raises(RuntimeError, match="column insert failed"):
        NativeCardWorkspaceAdapter(actor, service).create_project_board("Operations", None)


def test_native_card_creation_selects_server_side_leftmost_active_column() -> None:
    """Callers cannot select a destination; archive and input order are ignored."""

    project = SimpleNamespace(id=1)
    created: list[tuple[Any, ...]] = []
    card = {"uid": "card-one", "title": "First task"}
    service = SimpleNamespace(
        project=SimpleNamespace(get_by_id_like=lambda _uid: project),
        project_column=SimpleNamespace(
            get_api_list_by_project=lambda _project, limit: [
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


def test_native_metadata_save_returns_written_record_without_bulk_reload() -> None:
    project = SimpleNamespace(id=1)
    card = SimpleNamespace(id=2, project_id=1)
    saved = SimpleNamespace(key="summary", value="Ready")
    service = SimpleNamespace(
        project=SimpleNamespace(get_by_id_like=lambda _uid: project),
        card=SimpleNamespace(get_by_id_like=lambda _uid: card),
        metadata=SimpleNamespace(
            save=lambda *_args: saved,
            get_all_as_api=lambda *_args, **_kwargs: pytest.fail("bulk metadata query used"),
        ),
    )

    result = NativeCardWorkspaceAdapter(object(), service).save_public_card_metadata(
        "project-one",
        "card-one",
        "summary",
        "Ready",
        None,
    )

    assert result == {"summary": "Ready"}


def test_native_relationship_replacement_bounds_existing_relationships() -> None:
    project = SimpleNamespace(id=1)
    card = SimpleNamespace(id=2, project_id=1)
    limits: list[int] = []
    service = SimpleNamespace(
        project=SimpleNamespace(get_by_id_like=lambda _uid: project),
        card=SimpleNamespace(get_by_id_like=lambda _uid: card),
        app_setting=SimpleNamespace(get_api_global_relationship_list=lambda: []),
        card_relationship=SimpleNamespace(
            get_api_list_by_card=lambda _card, limit: (
                limits.append(limit),
                [{} for _ in range(MAX_NATIVE_SECTION_SOURCE + 1)],
            )[1]
        ),
    )

    with pytest.raises(ValueError, match="safe 100-item MCP source bound"):
        NativeCardWorkspaceAdapter(object(), service).replace_card_relationships(
            "project-one",
            "card-one",
            True,
            [],
        )

    assert limits == [MAX_NATIVE_SECTION_SOURCE + 1]
