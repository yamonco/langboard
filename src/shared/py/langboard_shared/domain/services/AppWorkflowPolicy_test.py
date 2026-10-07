"""App mapping retains explicit choices while current authority changes."""

import pytest
from ..models import ProjectColumn, WorkflowStageDefinition
from .AppWorkflowPolicy import (
    GITHUB_WORKFLOW_REQUIREMENTS,
    GLITCHTIP_WORKFLOW_REQUIREMENTS,
    WorkflowRequirements,
    resolve_app_workflow,
)


def facts():
    columns = [
        ProjectColumn(id=i + 1, project_id=10, name="Arbitrary display", workflow_stage=key)
        for i, key in enumerate(("active", "review", "closed"))
    ]
    stages = [WorkflowStageDefinition(key=key, name="Translated") for key in ("active", "review", "closed", "ready")]
    return columns, stages


def evaluate(columns, stages, explicit=None, authorized=None):
    return resolve_app_workflow(
        GITHUB_WORKFLOW_REQUIREMENTS,
        10,
        columns,
        stages,
        explicit or {},
        authorized_column_ids=frozenset(c.id for c in columns) if authorized is None else authorized,
    )


def test_unique_mapping_resolves_and_missing_optional_does_not_block():
    columns, stages = facts()
    result = evaluate(columns, stages)
    assert result.transitions_enabled
    assert [c.status for c in result.choices] == ["resolved", "resolved", "resolved", "missing"]
    assert [c.column_uid for c in result.choices[:3]] == [c.get_uid() for c in columns]
    assert GLITCHTIP_WORKFLOW_REQUIREMENTS.required == GITHUB_WORKFLOW_REQUIREMENTS.required


def test_explicit_mapping_survives_new_duplicate_and_removal_of_other_column():
    columns, stages = facts()
    choice = {"active": columns[0].get_uid()}
    duplicate = columns[0].model_copy(update={"id": 9})
    assert evaluate(columns + [duplicate], stages).choices[0].status == "ambiguous"
    assert not evaluate(columns + [duplicate], stages).transitions_enabled
    result = evaluate(columns + [duplicate], stages, choice)
    assert result.transitions_enabled and result.choices[0].column_uid == columns[0].get_uid()
    assert evaluate(columns, stages, choice).transitions_enabled


@pytest.mark.parametrize("change", ["deleted", "archive", "foreign", "stage", "permission", "registry"])
def test_stale_explicit_choice_never_falls_back_or_exposes_hidden_uid(change):
    columns, stages = facts()
    chosen = columns[0].get_uid()
    duplicate = columns[0].model_copy(update={"id": 9})
    if change == "deleted":
        from ...core.types import SafeDateTime

        columns[0].deleted_at = SafeDateTime.now()
    elif change == "archive":
        columns[0].is_archive = True
    elif change == "foreign":
        columns[0].project_id = 20
    elif change == "stage":
        columns[0].workflow_stage = "review"
    elif change == "registry":
        stages[0].is_active = False
    authorized = frozenset({2, 3, 9}) if change == "permission" else frozenset({1, 2, 3, 9})
    result = evaluate(columns + [duplicate], stages, {"active": chosen}, authorized)
    assert result.choices[0].status == "invalid"
    assert result.choices[0].column_uid is None
    assert not result.transitions_enabled


def test_missing_required_and_unclassified_named_column_never_infers_stage():
    columns, stages = facts()
    columns[0].workflow_stage = None
    columns[0].name = "active"
    assert evaluate(columns, stages).choices[0].status == "missing"
    assert not evaluate(columns, stages).transitions_enabled


def test_optional_explicit_invalid_blocks_transition_and_unknown_keys_rejected():
    columns, stages = facts()
    assert not evaluate(columns, stages, {"ready": "missing"}).transitions_enabled
    with pytest.raises(ValueError):
        evaluate(columns, stages, {"unknown": "missing"})
    for required, optional in [((), ()), (("active", "active"), ()), (("active",), ("active",)), (("",), ())]:
        with pytest.raises(ValueError):
            WorkflowRequirements(required, optional)


def test_optional_registry_stage_absence_does_not_require_board_changes():
    columns, stages = facts()
    assert evaluate(columns, stages[:3]).transitions_enabled
