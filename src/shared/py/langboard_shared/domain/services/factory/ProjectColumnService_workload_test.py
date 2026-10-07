"""API serialization retains physical counts and appends unfinished counts."""

import os


os.environ.setdefault("PROJECT_NAME", "langboard")
from types import SimpleNamespace
from unittest.mock import Mock
from .ProjectColumnService import ProjectColumnService


def test_api_columns_retain_existing_counts_and_add_batched_workload():
    column = SimpleNamespace(id=7, workflow_stage=None, description="", api_response=lambda: {"uid": "column", "name": "Stage"})
    repository = SimpleNamespace(
        get_all_by_project=Mock(return_value=[(column, 9)]),
        get_work_counts=Mock(return_value={7: {"open_count": 7, "incomplete_count": 4}}),
    )
    service = object.__new__(ProjectColumnService)
    service.repo = SimpleNamespace(project_column=repository, workflow_stage=SimpleNamespace(get_by_keys=Mock(return_value={})))
    assert service.get_api_list_by_project([1, 2]) == [
        {"uid": "column", "name": "Stage", "count": 9, "open_count": 7, "incomplete_count": 4,
         "workflow_counts_as_completed": None, "workflow_stage_description": "", "column_description": "", "workflow_guidance": "", "workflow_stage_status": "unclassified"}
    ]
    repository.get_work_counts.assert_called_once_with([1, 2])
