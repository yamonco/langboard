import os


os.environ.setdefault("PROJECT_NAME", "langboard")

from langboard_shared.domain.contracts.kanboard_import import (  # noqa: E402
    map_full_kanboard_export,
    map_kanboard_comment,
    map_kanboard_project,
)


PROJECT = {"id": 1, "name": "Test Project", "description": "A test"}
TASKS = [
    {"id": 10, "title": "Task A", "project_id": 1, "column_name": "Backlog", "priority": 2, "date_creation": 1700000000},
    {"id": 11, "title": "Task B", "project_id": 1, "column_name": "Done", "priority": 1, "date_creation": 1700000100},
    {"id": 12, "title": "Task C", "project_id": 2, "column_name": "Ready", "priority": 0},  # different project
]
COMMENTS = [
    {"id": 100, "task_id": 10, "comment": "First comment", "user_id": 5, "username": "alice", "date_creation": 1700000200},
    {"id": 101, "task_id": 11, "comment": "Second comment", "user_id": 6, "username": "bob", "date_creation": 1700000300},
    {"id": 102, "task_id": 99, "comment": "Orphan comment", "user_id": 7},  # task doesn't exist
]


class TestMapKanboardComment:
    def test_maps_basic_comment(self):
        result = map_kanboard_comment(COMMENTS[0])
        assert result["content"] == "First comment"
        assert result["source_username"] == "alice"
        assert "created_at" in result

    def test_returns_none_for_missing_id(self):
        assert map_kanboard_comment({"comment": "no id"}) is None

    def test_returns_none_for_missing_content(self):
        assert map_kanboard_comment({"id": 1}) is None


class TestMapKanboardProject:
    def test_maps_project_with_tasks(self):
        result = map_kanboard_project(PROJECT, TASKS, COMMENTS)
        assert result.title == "Test Project"
        assert len(result.cards) == 2  # only project_id=1 tasks
        assert len(result.comments) == 2  # comments for tasks 10,11

    def test_extracts_unique_columns(self):
        result = map_kanboard_project(PROJECT, TASKS, COMMENTS)
        col_names = [c["name"] for c in result.columns]
        assert "Backlog" in col_names
        assert "Done" in col_names
        assert "Ready" not in col_names  # that's project 2's column

    def test_empty_tasks_gets_default_columns(self):
        result = map_kanboard_project(PROJECT, [], [])
        assert len(result.columns) >= 3  # Backlog, Ready, In Progress...

    def test_orphan_comments_excluded(self):
        result = map_kanboard_project(PROJECT, TASKS, COMMENTS)
        comment_ids = [c["source_id"] for c in result.comments]
        assert "102" not in comment_ids


class TestMapFullKanboardExport:
    def test_processes_multiple_projects(self):
        projects = [PROJECT, {"id": 2, "name": "Second"}]
        result = map_full_kanboard_export(projects, TASKS, COMMENTS)
        assert result.total_projects == 2
        assert result.total_cards == 3  # all 3 tasks
        assert result.total_comments == 2  # only tasks 10,11 comments

    def test_errors_for_missing_project_id(self):
        result = map_full_kanboard_export([{"name": "No ID"}], [], [])
        assert len(result.errors) == 1
        assert result.total_projects == 0

    def test_empty_export(self):
        result = map_full_kanboard_export([], [], [])
        assert result.total_projects == 0
        assert result.projects == []
