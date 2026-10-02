"""API serialization retains physical counts and appends unfinished counts."""

import os


os.environ.setdefault("PROJECT_NAME", "langboard")
from types import SimpleNamespace
from unittest.mock import Mock
from .ProjectColumnService import ProjectColumnService


def test_api_columns_retain_existing_counts_and_add_batched_workload():
    column = SimpleNamespace(id=7, api_response=lambda: {"uid": "column", "name": "Stage"})
    repository = SimpleNamespace(
        get_all_by_project=Mock(return_value=[(column, 9)]),
        get_work_counts=Mock(return_value={7: {"open_count": 7, "incomplete_count": 4}}),
    )
    service = object.__new__(ProjectColumnService)
    service.repo = SimpleNamespace(project_column=repository)
    assert service.get_api_list_by_project([1, 2]) == [
        {"uid": "column", "name": "Stage", "count": 9, "open_count": 7, "incomplete_count": 4}
    ]
    repository.get_work_counts.assert_called_once_with([1, 2])
