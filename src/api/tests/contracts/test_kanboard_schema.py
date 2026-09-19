import os


os.environ.setdefault("PROJECT_NAME", "langboard")

from langboard_shared.domain.contracts.kanboard_schema import (  # noqa: E402
    map_kanboard_export,
    map_kanboard_row,
    normalize_column_name,
    normalize_priority,
)


def make_row(**overrides):
    base = {
        "id": 42,
        "title": "Test task",
        "description": "Body text",
        "project_name": "My Project",
        "column_name": "Work in Progress",
        "priority": 3,
        "date_creation": 1700000000,
        "date_due": 1750000000,
        "tags": "bug, urgent",
        "creator_username": "alice",
        "assignee_username": "bob",
    }
    base.update(overrides)
    return base


class TestMapKanboardRow:
    def test_maps_basic_fields(self):
        result = map_kanboard_row(make_row())
        assert result["source_id"] == 42
        assert result["title"] == "Test task"
        assert result["description"] == "Body text"
        assert result["source_project_name"] == "My Project"

    def test_normalizes_column_name(self):
        result = map_kanboard_row(make_row(column_name="Work in Progress"))
        assert result["normalized_column"] == "In Progress"

    def test_normalizes_priority(self):
        assert map_kanboard_row(make_row(priority=3))["priority_label"] == "P0"
        assert map_kanboard_row(make_row(priority=1))["priority_label"] == "P3"

    def test_converts_unix_timestamps(self):
        result = map_kanboard_row(make_row())
        assert "T" in result["source_created_at"]  # ISO format
        assert result["deadline_at"].startswith("20")

    def test_splits_tags(self):
        result = map_kanboard_row(make_row())
        assert result["tags"] == ["bug", "urgent"]

    def test_returns_none_for_missing_id(self):
        assert map_kanboard_row({"title": "no id"}) is None

    def test_returns_none_for_missing_title(self):
        assert map_kanboard_row({"id": 1}) is None

    def test_zero_timestamp_removed(self):
        result = map_kanboard_row(make_row(date_due=0))
        assert "deadline_at" not in result


class TestNormalizeColumnName:
    def test_backlog(self):
        assert normalize_column_name("backlog") == "Backlog"

    def test_case_insensitive(self):
        assert normalize_column_name("DONE") == "Done"

    def test_unknown_passthrough(self):
        assert normalize_column_name("Custom Stage") == "Custom Stage"


class TestNormalizePriority:
    def test_valid_priorities(self):
        assert normalize_priority(0) == "P2"
        assert normalize_priority(1) == "P3"
        assert normalize_priority(2) == "P1"
        assert normalize_priority(3) == "P0"

    def test_invalid_defaults_to_p2(self):
        assert normalize_priority("abc") == "P2"
        assert normalize_priority(-1) == "P2"


class TestMapKanboardExport:
    def test_processes_valid_rows(self):
        rows = [make_row(), make_row(id=43, title="Second"), {"id": 1, "description": "no title"}]
        result = map_kanboard_export(rows)
        assert result.valid_count == 2
        assert result.skipped_count == 1
        assert len(result.mapped_cards) == 2
        assert len(result.errors) == 1

    def test_collects_unique_columns(self):
        rows = [
            make_row(column_name="Backlog"),
            make_row(id=2, column_name="Done"),
            make_row(id=3, column_name="backlog"),  # duplicate normalized
        ]
        result = map_kanboard_export(rows)
        assert result.column_names == ["Backlog", "Done"]

    def test_empty_export(self):
        result = map_kanboard_export([])
        assert result.valid_count == 0
        assert result.mapped_cards == []
