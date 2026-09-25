import os


os.environ.setdefault("PROJECT_NAME", "langboard")

from langboard_shared.domain.contracts.kanboard_validation import (  # noqa: E402
    validate_kanboard_export,
)


VALID_PROJECTS = [{"id": 1, "name": "P1"}]
VALID_TASKS = [
    {"id": 10, "title": "T1", "project_id": 1, "column_name": "Backlog"},
    {"id": 11, "title": "T2", "project_id": 1, "column_name": "Done"},
]
VALID_COMMENTS = [
    {"id": 100, "task_id": 10, "comment": "ok"},
]


class TestValidExport:
    def test_valid_export_passes(self):
        report = validate_kanboard_export(VALID_PROJECTS, VALID_TASKS, VALID_COMMENTS)
        assert report.is_valid
        assert report.can_import
        assert report.errors == 0

    def test_summary_includes_counts(self):
        report = validate_kanboard_export(VALID_PROJECTS, VALID_TASKS, VALID_COMMENTS)
        assert "1 projects" in report.summary
        assert "2 cards" in report.summary


class TestErrors:
    def test_missing_task_title(self):
        tasks = [{"id": 10, "title": "", "project_id": 1}]
        report = validate_kanboard_export(VALID_PROJECTS, tasks, [])
        assert not report.is_valid
        assert not report.can_import
        assert report.errors == 1

    def test_missing_task_id(self):
        tasks = [{"title": "no id"}]
        report = validate_kanboard_export(VALID_PROJECTS, tasks, [])
        assert report.errors >= 1

    def test_missing_project_id(self):
        projects = [{"name": "no id"}]
        report = validate_kanboard_export(projects, [], [])
        assert report.errors >= 1


class TestWarnings:
    def test_duplicate_task_id(self):
        tasks = [
            {"id": 10, "title": "A", "project_id": 1},
            {"id": 10, "title": "B", "project_id": 1},
        ]
        report = validate_kanboard_export(VALID_PROJECTS, tasks, [])
        assert report.warnings >= 1

    def test_unknown_project_reference(self):
        tasks = [{"id": 10, "title": "A", "project_id": 99}]
        report = validate_kanboard_export(VALID_PROJECTS, tasks, [])
        assert report.warnings >= 1

    def test_orphan_comment(self):
        comments = [{"id": 1, "task_id": 99, "comment": "orphan"}]
        report = validate_kanboard_export(VALID_PROJECTS, VALID_TASKS, comments)
        assert report.warnings >= 1

    def test_truncated_description(self):
        tasks = [{"id": 10, "title": "A", "project_id": 1, "description": "x" * 40000}]
        report = validate_kanboard_export(VALID_PROJECTS, tasks, [])
        assert report.warnings >= 1


class TestEdgeCases:
    def test_empty_export(self):
        report = validate_kanboard_export([], [], [])
        assert report.is_valid
        assert report.total_issues == 0

    def test_high_column_count(self):
        tasks = [{"id": i, "title": f"T{i}", "project_id": 1, "column_name": f"col{i}"} for i in range(15)]
        report = validate_kanboard_export(VALID_PROJECTS, tasks, [])
        assert report.warnings >= 1
