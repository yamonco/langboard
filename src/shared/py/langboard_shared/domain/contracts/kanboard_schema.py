"""Kanboard data mapping contract: import schema, field mapping, validation.

Defines the accepted Kanboard export fields and their Langboard equivalents,
plus a pure mapping function that converts Kanboard JSON to Langboard import
payloads.
"""

from dataclasses import dataclass, field
from typing import Any


# Kanboard export field → Langboard field mapping
KANBOARD_FIELD_MAP: dict[str, str] = {
    "id": "source_id",
    "title": "title",
    "description": "description",
    "project_id": "source_project_id",
    "column_id": "source_column_id",
    "owner_id": "source_owner_id",
    "creator_id": "source_creator_id",
    "color_id": "label_color",
    "project_name": "source_project_name",
    "column_name": "source_column_name",
    "assignee_username": "source_assignee",
    "creator_username": "source_creator",
    "date_creation": "source_created_at",
    "date_modification": "source_updated_at",
    "date_due": "deadline_at",
    "date_started": "source_started_at",
    "time_spent": "source_time_spent",
    "time_estimated": "source_time_estimated",
    "priority": "priority",
    "score": "score",
    "reference": "external_reference",
    "tags": "tags",
    "category": "label",
    "swimlane": "source_swimlane",
    "url": "source_url",
}

# Required fields — import fails if missing
REQUIRED_FIELDS: frozenset[str] = frozenset({"id", "title"})

# Column name normalization: Kanboard → Langboard lifecycle
COLUMN_NORMALIZATION: dict[str, str] = {
    "backlog": "Backlog",
    "ready": "Ready",
    "work in progress": "In Progress",
    "in progress": "In Progress",
    "doing": "In Progress",
    "done": "Done",
    "closed": "Done",
    "archive": "Archive",
}

# Kanboard priority (1=lowest, 3=highest) → Langboard label
PRIORITY_LABELS: dict[int, str] = {
    0: "P2",
    1: "P3",
    2: "P1",
    3: "P0",
}


@dataclass
class KanboardImportResult:
    """Result of mapping Kanboard rows to Langboard payloads."""

    valid_count: int = 0
    skipped_count: int = 0
    errors: list[str] = field(default_factory=list)
    mapped_cards: list[dict[str, Any]] = field(default_factory=list)
    column_names: list[str] = field(default_factory=list)


def normalize_column_name(kanboard_column: str) -> str:
    """Normalize a Kanboard column name to a Langboard column name."""
    return COLUMN_NORMALIZATION.get(kanboard_column.strip().lower(), kanboard_column.strip())


def normalize_priority(kanboard_priority: int | str) -> str:
    """Map a Kanboard priority (0-3) to a Langboard priority label."""
    try:
        p = int(kanboard_priority)
    except (ValueError, TypeError):
        return "P2"
    return PRIORITY_LABELS.get(p, "P2")


def map_kanboard_row(row: dict[str, Any]) -> dict[str, Any] | None:
    """Map a single Kanboard export row to a Langboard card payload.

    Returns None if required fields are missing.
    """
    for req in REQUIRED_FIELDS:
        if req not in row or row[req] is None:
            return None

    mapped: dict[str, Any] = {}
    for kanboard_field, langboard_field in KANBOARD_FIELD_MAP.items():
        if kanboard_field in row and row[kanboard_field] is not None:
            mapped[langboard_field] = row[kanboard_field]

    # Normalizations
    if "source_column_name" in mapped:
        mapped["normalized_column"] = normalize_column_name(mapped["source_column_name"])

    if "priority" in mapped:
        mapped["priority_label"] = normalize_priority(mapped.pop("priority"))

    # Kanboard dates are Unix timestamps
    for date_field in ("source_created_at", "source_updated_at", "deadline_at"):
        if date_field in mapped:
            try:
                ts = int(mapped[date_field])
                if ts > 0:
                    from datetime import datetime, timezone
                    mapped[date_field] = datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()
                else:
                    del mapped[date_field]
            except (ValueError, TypeError):
                del mapped[date_field]

    # Tags: Kanboard uses comma-separated string
    if "tags" in mapped and isinstance(mapped["tags"], str):
        mapped["tags"] = [t.strip() for t in mapped["tags"].split(",") if t.strip()]

    return mapped


def map_kanboard_export(rows: list[dict[str, Any]]) -> KanboardImportResult:
    """Map a full Kanboard export to Langboard import payloads."""
    result = KanboardImportResult()

    for i, row in enumerate(rows):
        mapped = map_kanboard_row(row)
        if mapped is None:
            result.skipped_count += 1
            missing = [f for f in REQUIRED_FIELDS if f not in row]
            result.errors.append(f"Row {i}: missing required fields {missing}")
            continue

        result.valid_count += 1
        result.mapped_cards.append(mapped)

        col = mapped.get("normalized_column", "")
        if col and col not in result.column_names:
            result.column_names.append(col)

    result.column_names.sort()
    return result
