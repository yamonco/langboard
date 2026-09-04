import os
from types import SimpleNamespace
from typing import Any
import pytest


os.environ.setdefault("PROJECT_NAME", "langboard")

from langboard.card_workspace.domain import CardDescriptionPatch, ExactTextReplacement  # noqa: E402
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


def test_native_cardify_reads_back_created_card() -> None:
    """Cardification returns the exact card linked by the source checkitem."""

    calls: list[tuple[Any, ...]] = []
    item = SimpleNamespace(cardified_id=None)
    persisted_item = SimpleNamespace(cardified_id=None)
    created = SimpleNamespace(board_api_response=lambda *_args: {"uid": "created-card", "title": "Promoted task"})

    def cardify(*args: Any) -> bool:
        calls.append(args)
        persisted_item.cardified_id = 42
        return True

    project = SimpleNamespace(id=7)
    source_card = SimpleNamespace(project_id=7)
    service = SimpleNamespace(
        checkitem=SimpleNamespace(cardify=cardify),
        card=SimpleNamespace(get_by_id_like=lambda card_id: created if card_id == 42 else None),
        project_column=SimpleNamespace(get_by_id_like=lambda _uid: SimpleNamespace(project_id=7, is_archive=False)),
    )
    actor = object()
    adapter = NativeCardWorkspaceAdapter(actor, service)
    adapter._ensure_project_card = lambda *_args: (project, source_card)  # type: ignore[method-assign]
    adapter._ensure_checkitem = lambda *_args: persisted_item if calls else item  # type: ignore[method-assign]

    result = adapter.cardify_card_checkitem("project", "card", "item", "column")

    assert result == {"uid": "created-card", "title": "Promoted task"}
    assert calls == [(actor, "project", "card", item, "column")]
    assert item.cardified_id is None


def test_native_cardify_rejects_column_from_another_project() -> None:
    """A caller cannot cardify into a column outside the source project."""

    service = SimpleNamespace(
        project_column=SimpleNamespace(get_by_id_like=lambda _uid: SimpleNamespace(project_id=99, is_archive=False)),
        checkitem=SimpleNamespace(cardify=lambda *_args: pytest.fail("cardify must not run")),
    )
    adapter = NativeCardWorkspaceAdapter(object(), service)
    adapter._ensure_project_card = lambda *_args: (  # type: ignore[method-assign]
        SimpleNamespace(id=7),
        SimpleNamespace(project_id=7),
    )
    adapter._ensure_checkitem = lambda *_args: SimpleNamespace(  # type: ignore[method-assign]
        cardified_id=None
    )

    with pytest.raises(ValueError, match="not active in the source project"):
        adapter.cardify_card_checkitem("project", "card", "item", "foreign-column")


def test_native_project_creation_uses_template_service(monkeypatch: pytest.MonkeyPatch) -> None:
    """The native project API, not Hermes, owns template selection and board shape."""

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


def test_native_description_patch_compares_before_updating() -> None:
    """The adapter passes only the locally patched rich-text value to the native service."""

    project = SimpleNamespace(id=1)
    card = SimpleNamespace(project_id=1, description=SimpleNamespace(content="before old after"))
    updates: list[tuple[Any, ...]] = []
    service = SimpleNamespace(
        project=SimpleNamespace(get_by_id_like=lambda _uid: project),
        card=SimpleNamespace(
            get_by_id_like=lambda _uid: card,
            update=lambda *args: (updates.append(args), {"description": True})[1],
        ),
    )

    result = NativeCardWorkspaceAdapter(object(), service).patch_card_description(
        "project-one",
        "card-one",
        CardDescriptionPatch((ExactTextReplacement(old_text="old", new_text="new"),)),
    )

    assert result == "before new after"
    assert updates[0][1:3] == (project, card)
    assert updates[0][3]["description"].content == "before new after"


def test_native_description_read_revision_can_be_used_for_multi_hunk_patch() -> None:
    """A native editor wrapper must not produce a revision of its JSON envelope."""

    from langboard.card_workspace.application.projections import bounded_text
    from langboard.card_workspace.domain import CardBundleSection
    from langboard_shared.core.db import EditorContentModel

    original = "ALPHA=before\nBETA=keep\nGAMMA=before"
    editor = EditorContentModel(content=original)
    service, _ = _service()
    card = SimpleNamespace(
        project_id=1,
        project_column_id=2,
        description=editor,
        api_response=lambda: {"uid": "c1", "description": editor.model_dump()},
    )
    service.card.get_by_id_like = lambda _uid: card
    updates: list[tuple[Any, ...]] = []
    service.card.update = lambda *args: (updates.append(args), True)[1]
    adapter = NativeCardWorkspaceAdapter(object(), service)
    source = adapter.get_card_bundle_source("p1", "c1", frozenset({"description"}))
    assert source is not None
    text = bounded_text(source.details["description"], CardBundleSection.CoreDescription)
    assert text.content == original
    assert text.format == "text"

    result = adapter.patch_card_description(
        "p1",
        "c1",
        CardDescriptionPatch(
            (
                ExactTextReplacement(old_text="ALPHA=before", new_text="ALPHA=after"),
                ExactTextReplacement(old_text="GAMMA=before", new_text="GAMMA=after"),
            ),
            expected_revision=text.revision,
        ),
    )
    assert result == "ALPHA=after\nBETA=keep\nGAMMA=after"
    assert len(updates) == 1
