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
from langboard.mcp_tools import CardMcp, ProjectMcp  # noqa: E402


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


def test_native_source_projects_linked_wiki_content_without_task_sections() -> None:
    project = SimpleNamespace(id=1)
    card = SimpleNamespace(project_id=1, project_column_id=2, is_linked_resource=True)
    column = SimpleNamespace(id=2, project_id=1, name="Reference")
    actor = object()
    get_details = Mock(
        return_value={
            "uid": "c1",
            "title": "",
            "project_column_uid": "column-1",
            "project_column_name": "Reference",
            "linked_resource": {
                "status": "available",
                "title": "Runbook",
                "content": {"content": "Canonical Wiki body"},
            },
        }
    )
    service = SimpleNamespace(
        project=SimpleNamespace(get_by_id_like=lambda _uid: project),
        project_column=SimpleNamespace(get_by_id_like=lambda _uid: column),
        card=SimpleNamespace(get_by_id_like=lambda _uid: card, get_details=get_details),
    )

    source = NativeCardWorkspaceAdapter(actor, service).get_card_bundle_source(
        "p1",
        "c1",
        frozenset({"description", "people", "checklists", "attachments", "metadata", "automation.bot_scopes"}),
    )

    assert source is not None
    assert source.details["title"] == "Runbook"
    assert source.details["description"] == {"content": "Canonical Wiki body"}
    assert source.checklists == []
    assert source.attachments == []
    assert source.metadata == {}
    assert source.bot_scopes == []
    assert source.bot_schedules == []
    get_details.assert_called_once_with(project, card, actor, limit=MAX_NATIVE_SECTION_SOURCE + 1)


def test_native_checkitem_continuation_reads_only_the_requested_checklist() -> None:
    project = SimpleNamespace(id=1)
    card = SimpleNamespace(id=2, project_id=1, project_column_id=3, api_response=lambda: {"uid": "c1"})
    column = SimpleNamespace(id=3, project_id=1, name="Backlog")
    checklist = SimpleNamespace(id=4, card_id=2, api_response=lambda: {"uid": "cl1", "title": "Checklist"})
    calls: list[tuple[Any, Any, int]] = []
    service = SimpleNamespace(
        project=SimpleNamespace(get_by_id_like=lambda _uid: project),
        project_column=SimpleNamespace(get_by_id_like=lambda _uid: column),
        card=SimpleNamespace(
            get_by_id_like=lambda _uid: card,
            can_delete=lambda actor, target: False,
        ),
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
        "p1", "c1", frozenset({"checkitems:cl1"})
    )

    assert source is not None
    assert source.checklists[0]["checkitems"] == [{"uid": "ci1", "title": "Item"}]
    assert calls == [(card, checklist, MAX_NATIVE_SECTION_SOURCE + 1)]


def test_card_mcp_cardify_reads_back_created_card(monkeypatch: pytest.MonkeyPatch) -> None:
    """Cardification returns the exact card linked by the source checkitem."""

    calls: list[tuple[Any, ...]] = []
    item = SimpleNamespace(checklist_id=9, cardified_id=None)
    persisted_item = SimpleNamespace(checklist_id=9, cardified_id=None)
    created = SimpleNamespace(
        board_api_response=lambda *_args: {"uid": "created-card", "title": "Promoted task", "private": "hidden"}
    )

    def cardify(*args: Any) -> bool:
        calls.append(args)
        persisted_item.cardified_id = 42
        return True

    project = SimpleNamespace(id=7)
    source_card = SimpleNamespace(id=8, project_id=7, is_linked_resource=False)
    monkeypatch.setattr(CardMcp, "_require_task_card", lambda *_args: (project, source_card))
    service = SimpleNamespace(
        checkitem=SimpleNamespace(cardify=cardify, get_by_id_like=lambda _uid: persisted_item if calls else item),
        checklist=SimpleNamespace(get_by_id_like=lambda _uid: SimpleNamespace(card_id=8)),
        card=SimpleNamespace(get_by_id_like=lambda card_id: created if card_id == 42 else None),
        project_column=SimpleNamespace(get_by_id_like=lambda _uid: SimpleNamespace(project_id=7, is_archive=False)),
    )
    actor = object()
    result = CardMcp.cardify_card_checkitem(" project ", " card ", " item ", " column ", actor, service)

    assert result == {"card": {"uid": "created-card", "title": "Promoted task"}, "source_checkitem_uid": "item"}
    assert calls == [(actor, "project", "card", item, "column")]
    assert item.cardified_id is None


def test_card_mcp_cardify_rejects_column_from_another_project(monkeypatch: pytest.MonkeyPatch) -> None:
    """A caller cannot cardify into a column outside the source project."""

    service = SimpleNamespace(
        project_column=SimpleNamespace(get_by_id_like=lambda _uid: SimpleNamespace(project_id=99, is_archive=False)),
        checkitem=SimpleNamespace(cardify=lambda *_args: pytest.fail("cardify must not run")),
    )
    monkeypatch.setattr(
        CardMcp,
        "_require_task_card",
        lambda *_args: (SimpleNamespace(id=7), SimpleNamespace(id=8, project_id=7, is_linked_resource=False)),
    )
    service.checkitem.get_by_id_like = lambda _uid: SimpleNamespace(checklist_id=9, cardified_id=None)
    service.checklist = SimpleNamespace(get_by_id_like=lambda _uid: SimpleNamespace(card_id=8))

    with pytest.raises(ValueError, match="not active in the source project"):
        CardMcp.cardify_card_checkitem("project", "card", "item", "foreign-column", object(), service)


def test_project_mcp_creation_uses_template_service() -> None:
    """Both project creation tools use the project owner without a card workspace port."""

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
    result = CardMcp.provision_project(" Operations ", actor, service, "Room board")
    canonical = ProjectMcp.create_project(" Operations ", "Room board", "Other", actor, service, "SI")

    assert create_project_calls == [
        (actor, "Operations", "Room board", "Other", None, False),
        (actor, "Operations", "Room board", "Other", "SI", False),
    ]
    assert canonical == {"project_uid": "project-one"}
    assert result["project"] == {
        "uid": "project-one",
        "title": "Operations",
        "project_type": "Other",
        "url": "http://localhost:5173/board/project-one",
        "template": "SI",
    }
    assert [column["name"] for column in result["columns"]] == names
    with pytest.raises(ValueError, match="Project title"):
        ProjectMcp.create_project(" ", None, "Other", actor, service)
    with pytest.raises(ValueError, match="Template name"):
        CardMcp.provision_project("Operations", actor, service, template_name=" ")
    assert len(create_project_calls) == 2


def test_project_mcp_creation_propagates_template_failure() -> None:
    """The project owner failure is not hidden by the compatibility alias."""

    class Actor:
        pass

    actor = Actor()
    service = SimpleNamespace(
        project_template=SimpleNamespace(
            create_project=lambda *_args: (_ for _ in ()).throw(RuntimeError("column insert failed"))
        )
    )
    with pytest.raises(RuntimeError, match="column insert failed"):
        CardMcp.provision_project("Operations", actor, service)


def test_card_mcp_creation_selects_server_side_leftmost_active_column() -> None:
    """Callers cannot select a destination; archive and input order are ignored."""

    project = SimpleNamespace(id=1)
    created: list[tuple[Any, ...]] = []
    card = {"uid": "card-one", "title": "First task"}
    service = SimpleNamespace(
        project=SimpleNamespace(
            get_by_id_like=lambda _uid: project,
            get_api_assigned_user_list=lambda _project, where_user_in: [{"uid": "known"}],
        ),
        project_column=SimpleNamespace(
            get_api_list_by_project=lambda _project: [
                {"uid": "done", "name": "Done", "order": 20, "is_archive": False},
                {"uid": "archive", "name": "Archive", "order": -1, "is_archive": True},
                {"uid": "backlog", "name": "Backlog", "order": 10, "is_archive": False},
            ]
        ),
        card=SimpleNamespace(create=lambda *args: (created.append(args), (object(), card))[1]),
    )

    actor = object()
    result = CardMcp.create_card_in_leftmost_column("project-one", " First task ", actor, service)
    canonical = CardMcp.create_card("project-one", "leftmost", "Second task", None, None, actor, service)

    assert created[0][2] == "backlog"
    assert created[0][3] == "First task"
    assert created[1][2] == "backlog"
    assert canonical == card
    assert result == {
        "card": card,
        "column": {"uid": "backlog", "name": "Backlog"},
    }
    with pytest.raises(ValueError, match="not active"):
        CardMcp.create_card("project-one", "foreign-column", "Unsafe", None, None, actor, service)
    with pytest.raises(ValueError, match="duplicate"):
        CardMcp.create_card("project-one", "leftmost", "Unsafe", None, ["known", "known"], actor, service)
    with pytest.raises(ValueError, match="Unknown project member"):
        CardMcp.create_card("project-one", "leftmost", "Unsafe", None, ["unknown"], actor, service)
    assert len(created) == 2


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


@pytest.mark.parametrize(("before", "after"), [("", "first body"), ("existing", "")])
def test_native_description_replacement_supports_empty_bodies(before: str, after: str) -> None:
    """A CAS-guarded whole-body write can initialize or clear a description."""

    project = SimpleNamespace(id=1)
    card = SimpleNamespace(project_id=1, description=SimpleNamespace(content=before))
    updates: list[tuple[Any, ...]] = []
    service = SimpleNamespace(
        project=SimpleNamespace(get_by_id_like=lambda _uid: project),
        card=SimpleNamespace(
            get_by_id_like=lambda _uid: card,
            update=lambda *args, **kwargs: (updates.append((*args, kwargs)), {"description": True})[1],
        ),
    )

    result = NativeCardWorkspaceAdapter(object(), service).replace_card_description(
        "project-one", "card-one", after, projection_revision(before)
    )

    assert result == after
    assert updates[0][3]["description"].content == after
    assert updates[0][4] == {"expected_description": before}


def test_native_description_replacement_rejects_stale_revision_before_write() -> None:
    """A whole-body replacement never overwrites content that changed after review."""

    project = SimpleNamespace(id=1)
    card = SimpleNamespace(project_id=1, description=SimpleNamespace(content="current"))
    update = Mock()
    service = SimpleNamespace(
        project=SimpleNamespace(get_by_id_like=lambda _uid: project),
        card=SimpleNamespace(get_by_id_like=lambda _uid: card, update=update),
    )

    with pytest.raises(DescriptionPatchConflict, match="revision does not match"):
        NativeCardWorkspaceAdapter(object(), service).replace_card_description(
            "project-one", "card-one", "replacement", projection_revision("stale")
        )

    update.assert_not_called()


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
    card = SimpleNamespace(description=EditorContentModel(content="before"), is_linked_resource=False)
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
