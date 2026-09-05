"""Colocated executable proof for exact paging and non-destructive appends."""

from dataclasses import replace
import pytest
from .application import WikiRepository, append_wiki, read_wiki
from .domain import WikiSnapshot, WikiValidationError, append_content, content_page


def test_pages_reassemble_unicode_markdown_exactly() -> None:
    """Paging never normalizes addresses, Markdown, Unicode or line endings."""
    text = "# 규칙\r\n주소: 서울 👨‍💻\nhttps://example.com/a?x=1&b=2\n![image](image.png)\n" * 40
    snapshot = WikiSnapshot("w", "rules", text)
    pages, cursor = [], None
    while True:
        page = content_page(snapshot, "p/w", cursor, 37)
        pages.append(page["content"])
        cursor = page["next_cursor"]
        if cursor is None:
            break
    assert "".join(pages) == text
    assert snapshot.content == text


def test_cursor_cannot_mix_revisions_or_resources() -> None:
    """An old page or another wiki cannot silently contaminate a current read."""
    snapshot = WikiSnapshot("w", "rules", "abcdef")
    cursor = content_page(snapshot, "p/w", None, 2)["next_cursor"]
    for other, context in ((replace(snapshot, content="changed"), "p/w"), (snapshot, "p/other")):
        with pytest.raises(ValueError):
            content_page(other, context, cursor, 2)
    for limit in (0, 16001):
        with pytest.raises(ValueError):
            content_page(snapshot, "p/w", None, limit)
    for invalid_cursor in ("x" * 2049, "e30=", "W10=", "?"):
        with pytest.raises(ValueError):
            content_page(snapshot, "p/w", invalid_cursor, 2)


class MemoryWiki(WikiRepository):
    """Test port with explicit permission and compare-before-save semantics."""

    def __init__(self) -> None:
        self.value = WikiSnapshot("w", "rules", "KEEP\n![image](a.png)")
        self.allowed = True
        self.saves = 0

    def snapshot(self, project_uid: str, wiki_uid: str) -> WikiSnapshot:
        """Simulate permission revocation between pages."""
        if not self.allowed:
            raise PermissionError("private")
        return self.value

    def append(self, project_uid: str, wiki_uid: str, before: str, after: str) -> None:
        """Reject a stale write in the storage boundary."""
        assert self.value.content == before
        self.value = replace(self.value, content=after)
        self.saves += 1


def test_append_preserves_document_and_stale_retry_is_not_duplicate() -> None:
    """A replay cannot append the same contribution again with the old revision."""
    repository = MemoryWiki()
    original = repository.value
    result = append_wiki(repository, "p", "w", original.revision, "주소: exact/123")
    assert repository.value.content == original.content + "\n\n주소: exact/123"
    assert result["revision"] == repository.value.revision
    with pytest.raises(WikiValidationError):
        append_wiki(repository, "p", "w", original.revision, "주소: exact/123")
    assert repository.saves == 1
    with pytest.raises(WikiValidationError):
        append_content(repository.value, repository.value.revision, " ")


def test_permission_is_rechecked_on_every_page() -> None:
    """A continuation cursor is not a capability that bypasses revoked access."""
    repository = MemoryWiki()
    first = read_wiki(repository, "p", "w", None, 2)
    repository.allowed = False
    with pytest.raises(PermissionError):
        read_wiki(repository, "p", "w", first["next_cursor"], 2)
