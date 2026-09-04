from base64 import urlsafe_b64decode, urlsafe_b64encode
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from hashlib import sha256
from json import dumps, loads
from typing import Any


MAX_SECTION_LIMIT = 25
MAX_COMMENT_LIMIT = 20
MAX_CHECKITEMS_PER_CHECKLIST = 25
MAX_TEXT_CHARS = 8_000
MAX_METADATA_VALUE_CHARS = 4_000
MAX_METADATA_KEY_CHARS = 128
MAX_PROJECTION_KEY_CHARS = 64

_COMPACT_SECRET_FRAGMENTS = (
    "accesskey",
    "accesstoken",
    "apikey",
    "authorization",
    "clientsecret",
    "cookie",
    "credential",
    "password",
    "passwd",
    "privatekey",
    "refreshtoken",
    "secret",
    "session",
    "token",
)


class CardBundleInclude(StrEnum):
    """Optional sections available in the bounded card aggregate."""

    Description = "description"
    People = "people"
    Classification = "classification"
    Checklists = "checklists"
    Comments = "comments"
    Attachments = "attachments"
    Metadata = "metadata"
    Automation = "automation"


class CardBundleSection(StrEnum):
    """Independently pageable sections in an agent card projection."""

    CoreDescription = "core.description"
    People = "people"
    Labels = "classification.labels"
    Relationships = "classification.relationships"
    Checklists = "checklists"
    Comments = "comments"
    Attachments = "attachments"
    Metadata = "metadata"
    BotScopes = "automation.bot_scopes"
    BotSchedules = "automation.bot_schedules"


@dataclass(frozen=True)
class ExactTextReplacement:
    """One conflict-detecting replacement inside a card description."""

    old_text: str
    new_text: str

    def __post_init__(self) -> None:
        if not isinstance(self.old_text, str) or not self.old_text:
            raise ValueError("old_text must not be empty")
        if not isinstance(self.new_text, str):
            raise ValueError("new_text must be a string")
        if self.old_text == self.new_text:
            raise ValueError("old_text and new_text must differ")

    def apply(self, content: str) -> str:
        """Replace exactly one match or fail without changing content."""

        matches = content.count(self.old_text)
        if matches == 0:
            raise ValueError("Card description changed after review: old_text was not found")
        if matches > 1:
            raise ValueError("Card description patch is ambiguous: old_text occurs more than once")
        return content.replace(self.old_text, self.new_text, 1)


@dataclass(frozen=True)
class ChecklistProjectionItem:
    """One caller-owned desired item in an idempotent checklist projection."""

    key: str
    title: str
    is_checked: bool = False
    deadline_at: str | None = None

    def __post_init__(self) -> None:
        if not _is_projection_key(self.key):
            raise ValueError("Checklist projection item key is invalid")
        if not isinstance(self.title, str) or not self.title.strip() or len(self.title) > 500:
            raise ValueError("Checklist projection item title is invalid")
        if not isinstance(self.is_checked, bool):
            raise ValueError("Checklist projection item checked state must be boolean")
        if self.deadline_at is not None:
            datetime.fromisoformat(self.deadline_at)


def require_projection_key(value: str) -> str:
    """Normalize a caller-owned stable key for one card integration."""

    normalized = value.strip() if isinstance(value, str) else ""
    if not _is_projection_key(normalized):
        raise ValueError("Checklist projection key is invalid")
    return normalized


def _is_projection_key(value: str) -> bool:
    return (
        bool(value)
        and len(value) <= MAX_PROJECTION_KEY_CHARS
        and all(character.isalnum() or character in ":._-" for character in value)
    )


@dataclass(frozen=True)
class CommentPage:
    """Validated comment page request for an agent card read."""

    limit: int = 5
    cursor: str | None = None

    def __post_init__(self) -> None:
        if isinstance(self.limit, bool) or not 1 <= self.limit <= MAX_COMMENT_LIMIT:
            raise ValueError(f"comments_limit must be between 1 and {MAX_COMMENT_LIMIT}")


@dataclass(frozen=True)
class CommentCursor:
    """Opaque, stable cursor built from the native comment ordering key."""

    created_at: str
    comment_uid: str

    def __post_init__(self) -> None:
        datetime.fromisoformat(self.created_at)
        if not self.comment_uid:
            raise ValueError("Comment cursor UID is required")

    def encode(self) -> str:
        """Encode the cursor without exposing its internal shape."""

        payload = dumps(
            {"v": 1, "created_at": self.created_at, "comment_uid": self.comment_uid},
            separators=(",", ":"),
            sort_keys=True,
        ).encode()
        return urlsafe_b64encode(payload).decode().rstrip("=")

    @classmethod
    def decode(cls, value: str) -> "CommentCursor":
        """Decode and validate an opaque comment cursor."""

        try:
            padding = "=" * (-len(value) % 4)
            payload = loads(urlsafe_b64decode(value + padding))
            if payload.get("v") != 1:
                raise ValueError("Unsupported cursor version")
            return cls(created_at=payload["created_at"], comment_uid=payload["comment_uid"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError("Invalid comments_cursor") from exc


@dataclass(frozen=True)
class SectionPage:
    """Validated page request shared by bounded card sections."""

    limit: int = 10
    cursor: str | None = None

    def __post_init__(self) -> None:
        if isinstance(self.limit, bool) or not 1 <= self.limit <= MAX_SECTION_LIMIT:
            raise ValueError(f"section_limit must be between 1 and {MAX_SECTION_LIMIT}")


@dataclass(frozen=True)
class SectionCursor:
    """Opaque continuation for one immutable projection revision."""

    section: str
    offset: int
    revision: str

    def __post_init__(self) -> None:
        if not self.section or len(self.section) > 160:
            raise ValueError("Section cursor name is invalid")
        if isinstance(self.offset, bool) or self.offset < 1:
            raise ValueError("Section cursor offset is invalid")
        if len(self.revision) != 64 or any(char not in "0123456789abcdef" for char in self.revision):
            raise ValueError("Section cursor revision is invalid")

    def encode(self) -> str:
        """Encode a versioned section continuation."""

        payload = dumps(
            {"v": 1, "section": self.section, "offset": self.offset, "revision": self.revision},
            separators=(",", ":"),
            sort_keys=True,
        ).encode()
        return urlsafe_b64encode(payload).decode().rstrip("=")

    @classmethod
    def decode(cls, value: str) -> "SectionCursor":
        """Decode a section continuation and reject malformed values."""

        try:
            padding = "=" * (-len(value) % 4)
            payload = loads(urlsafe_b64decode(value + padding))
            if not isinstance(payload, dict) or payload.get("v") != 1:
                raise ValueError("Unsupported cursor version")
            return cls(
                section=payload["section"],
                offset=payload["offset"],
                revision=payload["revision"],
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError("Invalid section_cursor") from exc


@dataclass(frozen=True)
class ProjectCardCursor:
    """Opaque keyset cursor for a project card list."""

    updated_at: str
    card_uid: str

    def __post_init__(self) -> None:
        datetime.fromisoformat(self.updated_at)
        if not self.card_uid:
            raise ValueError("Project card cursor UID is required")

    def encode(self) -> str:
        """Encode a project-card keyset cursor."""

        payload = dumps(
            {"v": 1, "updated_at": self.updated_at, "card_uid": self.card_uid},
            separators=(",", ":"),
            sort_keys=True,
        ).encode()
        return urlsafe_b64encode(payload).decode().rstrip("=")

    @classmethod
    def decode(cls, value: str) -> "ProjectCardCursor":
        """Decode and validate a project-card cursor."""

        try:
            padding = "=" * (-len(value) % 4)
            payload = loads(urlsafe_b64decode(value + padding))
            if not isinstance(payload, dict) or payload.get("v") != 1:
                raise ValueError("Unsupported cursor version")
            return cls(updated_at=payload["updated_at"], card_uid=payload["card_uid"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError("Invalid cards_cursor") from exc


def projection_revision(value: Any) -> str:
    """Return a stable content hash used to detect stale offset cursors."""

    encoded = dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True, default=str).encode()
    return sha256(encoded).hexdigest()


def is_public_metadata_key(key: str) -> bool:
    """Return whether a metadata key is safe for an external agent contract."""

    normalized = key.strip().lower()
    if not normalized or len(normalized) > MAX_METADATA_KEY_CHARS:
        return False
    if normalized.startswith(
        (
            "__",
            "system.",
            "system_",
            "system-",
            "_system",
            "internal.",
            "internal_",
            "internal-",
            "private.",
            "private_",
            "private-",
        )
    ):
        return False
    compact = "".join(char for char in normalized if char.isalnum())
    if any(fragment in compact for fragment in _COMPACT_SECRET_FRAGMENTS):
        return False
    return True


def require_public_metadata_key(key: str) -> str:
    """Normalize one public metadata key or fail closed."""

    normalized = key.strip()
    if not is_public_metadata_key(normalized):
        raise ValueError("Metadata key is reserved or secret-like")
    return normalized
