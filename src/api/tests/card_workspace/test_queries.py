import json
import pytest
from langboard.card_workspace.application.ports import (
    CardBundleSource,
    CommentPageSource,
    ProjectCardPageSource,
)
from langboard.card_workspace.application.queries import (
    get_card_bundle,
    get_project_identity,
    get_public_card_metadata,
    list_project_cards,
)
from langboard.card_workspace.domain import CardBundleInclude, CommentPage, SectionPage


class FakeQueryPort:
    """Deterministic native facts for projection contract tests."""

    def __init__(self) -> None:
        self.requested_sections: list[frozenset[str]] = []
        self.source = CardBundleSource(
            details={
                "uid": "c1",
                "title": "Bounded card",
                "description": "x" * 8_050,
                "created_at": "2026-08-04T10:00:00+09:00",
                "updated_at": "2026-08-04T11:00:00+09:00",
                "project_column_uid": "column-1",
                "project_column_name": "Backlog",
                "member_uids": ["assigned"],
                "project_members": [
                    {"uid": "assigned", "username": "member", "email": "member@example.com"},
                    {"uid": "unassigned", "username": "directory", "email": "directory@example.com"},
                ],
                "labels": [{"uid": f"l{i}", "name": f"Label {i}"} for i in range(30)],
                "relationships": [],
            },
            checklists=[
                {
                    "uid": "cl1",
                    "title": "Checklist",
                    "checkitems": [{"uid": f"ci{i}", "title": f"Item {i}", "private": "hidden"} for i in range(30)],
                }
            ],
            attachments=[
                {
                    "uid": "a1",
                    "name": "report.pdf",
                    "url": "https://storage.invalid/private?token=credential",
                    "storage_key": "private/key",
                    "user": {"uid": "assigned", "username": "member", "email": "member@example.com"},
                }
            ],
            metadata={
                "public.topic": "delivery",
                "public.long": "m" * 4_050,
                "__system.docling_documents": "raw extraction",
                "oauth.refresh_token": "credential",
            },
            bot_scopes=[{"uid": "s1", "bot_uid": "b1", "prompt": "internal prompt"}],
            bot_schedules=[{"uid": "bs1", "bot_uid": "b1", "status": "active", "token": "secret"}],
        )

    def get_card_bundle_source(
        self, project_uid: str, card_uid: str, requested_sections: frozenset[str]
    ) -> CardBundleSource | None:
        self.requested_sections.append(requested_sections)
        return self.source if (project_uid, card_uid) == ("p1", "c1") else None

    def get_comment_page(
        self,
        card_uid: str,
        limit: int,
        before_created_at: str | None,
        before_comment_uid: str | None,
    ) -> CommentPageSource:
        items = [
            {
                "uid": f"comment-{i}",
                "content": "y" * 9_000 if i == 0 else f"Comment {i}",
                "created_at": f"2026-08-04T10:0{i}:00+09:00",
                "user": {"uid": "assigned", "email": "member@example.com"},
                "reactions": {
                    "thumbs-up": ["u1", "u2"],
                    "secret": ["must-not-leak"],
                },
            }
            for i in range(limit)
        ]
        return CommentPageSource(items, 20, ("2026-08-04T10:00:00+09:00", "comment-0"))

    def get_project_card_page(
        self,
        project_uid: str,
        limit: int,
        before_updated_at: str | None,
        before_card_uid: str | None,
    ) -> ProjectCardPageSource:
        return ProjectCardPageSource(
            [
                {
                    "uid": "c1",
                    "title": "Visible",
                    "updated_at": "2026-08-04T11:00:00+09:00",
                    "description": "not included",
                    "project_column_uid": "column-1",
                }
            ],
            99,
            ("2026-08-04T11:00:00+09:00", "c1"),
        )

    def get_project_identity(self, project_uid: str) -> dict[str, object] | None:
        """Return a bounded workflow fixture for identity projection."""

        if project_uid != "p1":
            return None
        return {
            "uid": "p1",
            "title": "Delivery",
            "project_type": "Other",
            "url": "http://localhost/board/p1",
            "columns": {
                "items": [
                    {"uid": "backlog", "name": "Backlog", "order": 0},
                    {"uid": "doing", "name": "In Progress", "order": 1},
                    {"uid": "done", "name": "Done", "order": 2},
                ],
                "total_count": 3,
                "next_cursor": None,
                "limit": 100,
            },
        }

    def get_public_card_metadata(self, project_uid: str, card_uid: str) -> dict[str, str] | None:
        return self.source.metadata


def test_initial_card_bundle_is_bounded_and_privacy_preserving() -> None:
    """The initial aggregate exposes assigned facts only and emits independent cursors."""

    response = get_card_bundle(
        FakeQueryPort(),
        "p1",
        "c1",
        CommentPage(limit=2),
        SectionPage(limit=10),
        [
            CardBundleInclude.Description,
            CardBundleInclude.People,
            CardBundleInclude.Classification,
            CardBundleInclude.Checklists,
            CardBundleInclude.Comments,
            CardBundleInclude.Attachments,
            CardBundleInclude.Metadata,
            CardBundleInclude.Automation,
        ],
    )

    assert response.card is not None
    assert response.card.people.total_count == 1
    assert response.card.people.items == [{"uid": "assigned", "username": "member"}]
    assert len(response.card.classification.labels.items) == 10
    assert response.card.classification.labels.next_cursor
    assert response.card.core["description"]["total_chars"] == 8_050
    assert len(response.card.core["description"]["revision"]) == 64
    assert response.card.core["description"]["next_cursor"]
    checklist = response.card.checklists.items[0]
    assert len(checklist["checkitems"]) == 25
    assert checklist["checkitems_next_cursor"]
    assert response.card.comments.limit == 2
    assert response.card.comments.items[0]["content_total_chars"] == 9_000
    assert len(response.card.comments.items[0]["content"]) == 8_000
    assert response.card.comments.items[0]["content_truncated"] is True
    assert response.card.comments.items[0]["reactions"] == {"thumbs-up": ["u1", "u2"]}
    assert response.card.comments.items[0]["reaction_counts"] == {"thumbs-up": 2}
    attachment = response.card.attachments.items[0]  # type: ignore[union-attr]
    assert attachment["user"] == {"uid": "assigned", "username": "member"}
    assert "storage_key" not in attachment
    assert "url" not in attachment
    metadata = {entry["key"]: entry for entry in response.card.metadata.items}  # type: ignore[union-attr]
    assert set(metadata) == {"public.long", "public.topic"}
    assert metadata["public.long"]["truncated"] is True
    assert "prompt" not in response.card.automation.bot_scopes.items[0]  # type: ignore[union-attr]
    assert "token" not in response.card.automation.bot_schedules.items[0]  # type: ignore[union-attr]


def test_project_identity_exposes_only_bounded_move_destinations() -> None:
    """Agents can discover active columns without a second unsafe project tool."""

    response = get_project_identity(FakeQueryPort(), "p1")

    assert [column["name"] for column in response.columns.items] == [
        "Backlog",
        "In Progress",
        "Done",
    ]
    assert response.columns.total_count == 3
    assert response.columns.next_cursor is None


def test_checkitem_projection_exposes_only_cardified_card_identity() -> None:
    """Cardification can be read back without leaking the generated card body."""

    port = FakeQueryPort()
    port.source.checklists[0]["checkitems"][0]["cardified_card"] = {
        "uid": "promoted-card",
        "title": "Promoted task",
        "description": "must-not-leak",
        "created_at": "2026-08-04T12:00:00+09:00",
    }

    response = get_card_bundle(
        port,
        "p1",
        "c1",
        CommentPage(),
        SectionPage(),
        [CardBundleInclude.Checklists],
    )

    assert response.card is not None
    assert response.card.checklists.items[0]["checkitems"][0]["cardified_card"] == {
        "uid": "promoted-card",
        "title": "Promoted task",
        "created_at": "2026-08-04T12:00:00+09:00",
    }


def test_section_continuation_rejects_changed_projection() -> None:
    """Offset cursors fail closed if the native section changed between calls."""

    port = FakeQueryPort()
    first = get_card_bundle(
        port,
        "p1",
        "c1",
        CommentPage(),
        SectionPage(limit=10),
        [CardBundleInclude.Classification],
    )
    assert first.card is not None
    assert first.card.classification is not None
    cursor = first.card.classification.labels.next_cursor
    assert cursor
    port.source.details["labels"].append({"uid": "new", "name": "Changed"})

    with pytest.raises(ValueError, match="stale"):
        get_card_bundle(port, "p1", "c1", CommentPage(), SectionPage(limit=10, cursor=cursor))


def test_optional_native_sections_are_requested_lazily() -> None:
    """Default and comment reads fetch no unrelated native sections."""

    port = FakeQueryPort()
    first = get_card_bundle(port, "p1", "c1", CommentPage(limit=1), SectionPage(limit=10))
    assert first.card is not None
    assert port.requested_sections[0] == frozenset()
    assert first.card.model_dump(exclude_none=True) == {
        "core": {
            "uid": "c1",
            "title": "Bounded card",
            "created_at": "2026-08-04T10:00:00+09:00",
            "updated_at": "2026-08-04T11:00:00+09:00",
        },
        "workflow": {
            "project_column_uid": "column-1",
            "project_column_name": "Backlog",
        },
    }

    comments = get_card_bundle(
        port,
        "p1",
        "c1",
        CommentPage(limit=1),
        SectionPage(limit=10),
        [CardBundleInclude.Comments],
    )
    assert comments.card is not None
    assert comments.card.comments is not None
    comment_cursor = comments.card.comments.next_cursor
    assert comment_cursor

    get_card_bundle(
        port,
        "p1",
        "c1",
        CommentPage(limit=1, cursor=comment_cursor),
        SectionPage(limit=10),
    )

    assert port.requested_sections[1:] == [frozenset(), frozenset()]


def test_compact_default_removes_large_unused_sections() -> None:
    """The common identity/workflow read is materially smaller than an explicit full read."""

    compact = get_card_bundle(FakeQueryPort(), "p1", "c1", CommentPage(), SectionPage())
    full = get_card_bundle(
        FakeQueryPort(),
        "p1",
        "c1",
        CommentPage(),
        SectionPage(),
        list(CardBundleInclude),
    )

    compact_bytes = len(json.dumps(compact.model_dump(mode="json", exclude_none=True)).encode())
    full_bytes = len(json.dumps(full.model_dump(mode="json", exclude_none=True)).encode())

    assert compact_bytes < full_bytes / 10


def test_project_card_list_is_bounded_and_uses_opaque_keyset_cursor() -> None:
    """Project discovery does not expose descriptions or materialize an unbounded list."""

    response = list_project_cards(FakeQueryPort(), "p1", limit=1)

    assert response.cards.total_count == 99
    assert response.cards.next_cursor
    assert response.cards.items == [
        {
            "uid": "c1",
            "title": "Visible",
            "updated_at": "2026-08-04T11:00:00+09:00",
            "project_column_uid": "column-1",
        }
    ]


def test_public_metadata_exposes_opaque_continuation() -> None:
    """>limit public metadata remains reachable without exposing cursor internals."""

    port = FakeQueryPort()
    first = get_public_card_metadata(port, "p1", "c1", limit=1)
    assert first.total_count == 2
    assert first.next_cursor

    second = get_public_card_metadata(port, "p1", "c1", limit=1, cursor=first.next_cursor)

    assert second.items[0]["key"] != first.items[0]["key"]
