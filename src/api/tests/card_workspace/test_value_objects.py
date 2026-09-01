import pytest
from langboard.card_workspace.domain import (
    CommentCursor,
    CommentPage,
    SectionCursor,
    is_public_metadata_key,
)


def test_comment_cursor_round_trips_without_exposing_shape() -> None:
    """The public token must round-trip as an opaque URL-safe value."""

    cursor = CommentCursor(created_at="2026-08-04T12:30:00+09:00", comment_uid="01AbCdEfGhI")
    encoded = cursor.encode()

    assert "created_at" not in encoded
    assert CommentCursor.decode(encoded) == cursor


@pytest.mark.parametrize("limit", [0, 21])
def test_comment_page_rejects_unbounded_limits(limit: int) -> None:
    """Agent reads cannot request an unbounded comment result."""

    with pytest.raises(ValueError, match="between 1 and 20"):
        CommentPage(limit=limit)


def test_comment_cursor_rejects_invalid_payload() -> None:
    """Malformed cursors fail closed instead of restarting from page one."""

    with pytest.raises(ValueError, match="Invalid comments_cursor"):
        CommentCursor.decode("not-a-valid-cursor")


def test_section_cursor_round_trips_and_is_versioned() -> None:
    """Every non-comment collection continuation is opaque and revision-bound."""

    cursor = SectionCursor(section="metadata", offset=10, revision="a" * 64)

    assert SectionCursor.decode(cursor.encode()) == cursor


@pytest.mark.parametrize(
    "key",
    [
        "__system.docling_documents",
        "private.notes",
        "oauth.refresh_token",
        "api-key",
        "session.id",
        "apiToken",
        "clientSecret",
        "accessKeyId",
    ],
)
def test_secret_and_reserved_metadata_keys_fail_closed(key: str) -> None:
    """System and credential-like metadata can never enter the public contract."""

    assert not is_public_metadata_key(key)
