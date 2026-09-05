"""Pure, revision-bound wiki paging and append rules."""

import json
from abc import ABC, abstractmethod
from base64 import urlsafe_b64decode, urlsafe_b64encode
from dataclasses import dataclass
from hashlib import sha256
from typing import Any


class WikiValidationError(ValueError):
    """Invalid or stale wiki input detected before a save."""


@dataclass(frozen=True)
class WikiSnapshot:
    """Exact content of one authorized current or historical wiki version."""

    uid: str
    title: str
    content: str

    @property
    def revision(self) -> str:
        """Return an exact-content concurrency token."""
        return sha256(self.content.encode()).hexdigest()


class WikiRepository(ABC):
    """Authorization-aware wiki persistence boundary owned by the domain."""

    @abstractmethod
    def snapshot(self, project_uid: str, wiki_uid: str) -> WikiSnapshot:
        """Read only a currently accessible wiki."""

    @abstractmethod
    def append(self, project_uid: str, wiki_uid: str, before: str, after: str) -> None:
        """Compare and save an authorized append without overwriting concurrent edits."""


def content_page(snapshot: WikiSnapshot, context: str, cursor: str | None, limit: int) -> dict[str, Any]:
    """Return exact text without mutating it or combining different revisions."""
    if not 1 <= limit <= 16000:
        raise ValueError("limit must be between 1 and 16000 characters")
    offset = 0
    if cursor:
        if len(cursor) > 2048:
            raise ValueError("Invalid wiki cursor: exceeds 2048 characters")
        try:
            payload = json.loads(urlsafe_b64decode(cursor.encode()))
            if payload["context"] != context or payload["revision"] != snapshot.revision:
                raise ValueError("Wiki changed or cursor belongs to another resource; restart reading")
            offset = payload["offset"]
            if type(offset) is not int or not 0 <= offset <= len(snapshot.content):
                raise ValueError("Invalid wiki cursor offset")
        except (KeyError, TypeError, UnicodeError, json.JSONDecodeError) as exc:
            raise ValueError("Invalid wiki cursor") from exc
    end = min(offset + limit, len(snapshot.content))
    next_cursor = None
    if end < len(snapshot.content):
        next_cursor = urlsafe_b64encode(
            json.dumps({"context": context, "revision": snapshot.revision, "offset": end}).encode()
        ).decode()
    return {
        "wiki_uid": snapshot.uid,
        "title": snapshot.title,
        "revision": snapshot.revision,
        "content": snapshot.content[offset:end],
        "offset": offset,
        "end_offset": end,
        "total_characters": len(snapshot.content),
        "next_cursor": next_cursor,
    }


def append_content(snapshot: WikiSnapshot, expected_revision: str, text: str) -> str:
    """Preserve the whole previous document and reject stale or empty appends."""
    if snapshot.revision != expected_revision:
        raise WikiValidationError("Wiki changed after review; read it again before appending")
    if not text.strip() or len(text) > 32000:
        raise WikiValidationError("Append text must contain 1 to 32000 characters")
    return snapshot.content + ("\n\n" if snapshot.content else "") + text
