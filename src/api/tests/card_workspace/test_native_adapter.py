import os
from types import SimpleNamespace
from typing import Any
import pytest


os.environ.setdefault("PROJECT_NAME", "langboard")

from langboard.card_workspace.domain import (  # noqa: E402
    CardDescriptionPatch,
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
            update=lambda *args, **kwargs: (updates.append((*args, kwargs)), {"description": True})[1],
        ),
    )

    result = NativeCardWorkspaceAdapter(object(), service).patch_card_description(
        "project-one",
        "card-one",
        CardDescriptionPatch(
            (ExactTextReplacement(old_text="old", new_text="new"),), projection_revision("before old after")
        ),
    )

    assert result == "before new after"
    assert updates[0][1:3] == (project, card)
    assert updates[0][3]["description"].content == "before new after"
    assert updates[0][4] == {"expected_description": "before old after"}


def test_native_description_missing_revision_stops_before_lookup() -> None:
    """A revision-less patch is safely rejected before touching persistence."""
    from langboard.card_workspace.domain import DescriptionPatchConflict

    adapter = NativeCardWorkspaceAdapter(object(), SimpleNamespace())
    with pytest.raises(DescriptionPatchConflict, match="expected_revision is required"):
        adapter.patch_card_description("p", "c", CardDescriptionPatch((ExactTextReplacement("old", "new"),)))


@pytest.mark.parametrize("conflict", [True, False])
def test_native_description_classifies_only_conditional_save_conflicts(conflict: bool) -> None:
    """Only a known pre-commit race is translated; downstream failures remain unknown."""
    from langboard.card_workspace.domain import DescriptionPatchConflict
    from langboard_shared.core.exceptions.CardDescriptionConflict import CardDescriptionConflict

    project = SimpleNamespace(id=1)
    card = SimpleNamespace(project_id=1, description=SimpleNamespace(content="old"))

    def fail(*args: Any, **kwargs: Any) -> None:
        if conflict:
            raise CardDescriptionConflict("concurrent update")
        raise ValueError("post-save effect failed")

    service = SimpleNamespace(
        project=SimpleNamespace(get_by_id_like=lambda _uid: project),
        card=SimpleNamespace(get_by_id_like=lambda _uid: card, update=fail),
    )
    with pytest.raises(ValueError) as error:
        NativeCardWorkspaceAdapter(object(), service).patch_card_description(
            "p", "c", CardDescriptionPatch((ExactTextReplacement("old", "new"),), projection_revision("old"))
        )
    assert isinstance(error.value, DescriptionPatchConflict) is conflict


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
    service.card.update = lambda *args, **kwargs: (updates.append((*args, kwargs)), True)[1]
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


def test_native_description_patch_requires_revision_before_lookup() -> None:
    """A direct native caller cannot bypass the gateway's required revision."""

    adapter = NativeCardWorkspaceAdapter(object(), SimpleNamespace())
    with pytest.raises(ValueError, match="expected_revision is required"):
        adapter.patch_card_description("p", "c", CardDescriptionPatch((ExactTextReplacement("old", "new"),)))


def test_description_repository_rejects_stale_writer_and_preserves_other_fields(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Check SQL preservation; the explicit isolated PostgreSQL mode also races two writers."""

    from collections.abc import Iterator
    from contextlib import contextmanager
    from langboard_shared.core.db import DbSession, EditorContentModel
    from langboard_shared.domain.models import Card as NativeCard
    from langboard_shared.infrastructure.repositories.factory.CardRepository import CardRepository
    from sqlalchemy import create_engine, select
    from sqlalchemy.orm import Session
    from sqlalchemy.schema import CreateTable

    database_url = os.environ.get("LANGBOARD_DESCRIPTION_TEST_DATABASE_URL", "sqlite://")
    if database_url != "sqlite://":
        from sqlalchemy.engine import make_url

        target = make_url(database_url)
        assert target.host == "127.0.0.1" and target.database == "langboard_description_test"
    engine = create_engine(database_url)
    with engine.begin() as connection:
        connection.execute(CreateTable(NativeCard.__table__, include_foreign_key_constraints=[]))
    with engine.begin() as connection:
        connection.execute(
            NativeCard.__table__.insert().values(
                id=101,
                project_id=1,
                project_column_id=2,
                title="preserved title",
                order=0,
                description=EditorContentModel(content="original"),
            )
        )

    @contextmanager
    def isolated_session(readonly: bool) -> Iterator[DbSession]:
        assert not readonly
        with Session(engine, expire_on_commit=False) as session, session.begin():
            yield DbSession(session, readonly=False)

    monkeypatch.setattr(DbSession, "use", isolated_session)
    repository = CardRepository.__new__(CardRepository)
    first = NativeCard(
        id=101,
        project_id=1,
        project_column_id=2,
        title="stale title",
        description=EditorContentModel(content="first edit"),
    )
    second = NativeCard(
        id=101,
        project_id=1,
        project_column_id=2,
        title="other stale title",
        description=EditorContentModel(content="second edit"),
    )
    assert repository.update_description_if_current(first, "original") is True
    assert repository.update_description_if_current(second, "original") is False
    with engine.connect() as connection:
        row = connection.execute(select(NativeCard.__table__.c.title, NativeCard.__table__.c.description)).one()
    assert row.title == "preserved title"
    assert row.description.content == "first edit"
    if engine.dialect.name == "postgresql":
        from concurrent.futures import ThreadPoolExecutor
        from threading import Barrier
        from sqlalchemy import update

        with engine.begin() as connection:
            connection.execute(update(NativeCard.__table__).values(description=EditorContentModel(content="original")))
        barrier = Barrier(2, timeout=10)

        def write(candidate: NativeCard) -> bool:
            barrier.wait()
            return repository.update_description_if_current(candidate, "original")

        with ThreadPoolExecutor(max_workers=2) as workers:
            results = list(workers.map(write, (first, second)))
        assert sorted(results) == [False, True]
        with engine.connect() as connection:
            final = connection.execute(select(NativeCard.__table__.c.title, NativeCard.__table__.c.description)).one()
        assert final.title == "preserved title"
        assert final.description.content == ("first edit" if results[0] else "second edit")
    engine.dispose()


@pytest.mark.parametrize("saved", [False, True])
def test_conditional_description_emits_effects_only_after_save(monkeypatch: pytest.MonkeyPatch, saved: bool) -> None:
    """Rejected writes emit no notifications, activities, bot events or realtime updates."""

    from unittest.mock import Mock
    from langboard_shared.core.db import EditorContentModel
    from langboard_shared.core.exceptions.CardDescriptionConflict import CardDescriptionConflict
    from langboard_shared.domain.services.factory.CardService import CardService
    from langboard_shared.helpers import InfraHelper
    from langboard_shared.publishers import CardPublisher
    from langboard_shared.tasks.activities import CardActivityTask
    from langboard_shared.tasks.bots import CardBotTask

    project = SimpleNamespace(id=1)
    card = SimpleNamespace(description=EditorContentModel(content="before"))
    conditional = Mock(return_value=saved)
    unconditional = Mock()
    service = CardService(
        Mock(),
        Mock(),
        SimpleNamespace(
            card=SimpleNamespace(
                update_description_if_current=conditional,
                update=unconditional,
            )
        ),
    )
    notifications = Mock()
    service._get_service = Mock(return_value=notifications)
    monkeypatch.setattr(InfraHelper, "get_records_with_foreign_by_params", lambda *_args: (project, card))
    effects = [Mock(), Mock(), Mock()]
    monkeypatch.setattr(CardPublisher, "updated", effects[0])
    monkeypatch.setattr(CardActivityTask, "card_updated", effects[1])
    monkeypatch.setattr(CardBotTask, "card_updated", effects[2])

    def execute() -> Any:
        return service.update(
            object(), project, card, {"description": EditorContentModel(content="after")}, expected_description="before"
        )

    if saved:
        assert execute() is not None
        for effect in effects:
            effect.assert_called_once()
        notifications.notify_mentioned_in_card.assert_called_once()
    else:
        with pytest.raises(CardDescriptionConflict, match="concurrent update"):
            execute()
        for effect in effects:
            effect.assert_not_called()
        notifications.notify_mentioned_in_card.assert_not_called()
    conditional.assert_called_once_with(card, "before")
    unconditional.assert_not_called()
