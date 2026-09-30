import pytest
from .CardWorkState import project_work_state


def state(**changes):
    return project_work_state(
        **{
            "card_uid": "card",
            "workflow_stage": None,
            "archived": False,
            "linked_resource": False,
            "total": 0,
            "completed": 0,
            "started": 0,
            "paused": 0,
            **changes,
        }
    )


@pytest.mark.parametrize("stage", [None, "Done", "Check", "Study", "회의록"])
def test_display_names_never_classify_workflow(stage):
    result = state(workflow_stage=stage)
    assert result["workflow_stage"] is None
    assert result["verification_state"] == "unverified"
    assert result["blocker_state"] is None
    assert result["active_queue_eligible"] is None


@pytest.mark.parametrize("stage", ["backlog", "ready", "active", "review", "closed", "reference"])
def test_explicit_semantics_are_independent_of_verification(stage):
    result = state(workflow_stage=stage)
    assert result["workflow_stage"] == stage
    assert result["verification_state"] == "unverified"


@pytest.mark.parametrize("completed", [1, 2])
def test_partial_and_all_checkitems_never_establish_approval(completed):
    result = state(workflow_stage="active", total=2, completed=completed)
    assert result["verification_state"] == "partial"
    assert result["active_queue_eligible"] is None
    assert bool(result["state_inconsistency"]) == (completed == 2)


def test_archive_retains_running_timer_diagnostic_and_excludes_queue():
    result = state(archived=True, started=1, paused=1)
    assert result["execution_state"] == "human_active"
    assert result["active_queue_eligible"] is False
    assert result["state_inconsistency"][0]["code"] == "archived_with_running_timer"
    assert result["state_inconsistency"][0]["source_ref"] == "card:card/checkitems"


def test_paused_and_unknown_agent_lifecycle_are_distinct():
    assert state(paused=1)["execution_state"] == "paused"
    assert state()["execution_state"] is None


def test_linked_wiki_is_material_not_completed_work():
    result = state(linked_resource=True)
    assert result["material_kind"] == "wiki-like"
    assert result["verification_state"] == "not_required"
    assert result["active_queue_eligible"] is False


def test_closed_open_checkitems_are_diagnosed_without_correcting_workflow():
    result = state(workflow_stage="closed", total=2, completed=1)
    assert result["workflow_stage"] == "closed"
    assert result["state_inconsistency"][0]["code"] == "closed_with_open_checkitems"


def test_known_dependency_blocks_queue_but_does_not_infer_approval():
    result = state(direct_blockers=[{"accessible": True, "card_uid": "parent"}])
    assert result["blocker_state"] == "blocked"
    assert result["active_queue_eligible"] is False
    assert result["verification_state"] == "unverified"
    assert any(reason["source_ref"] == "card:parent" for reason in result["reasons"])


def test_clear_dependencies_do_not_infer_clear_input_or_approval_gates():
    result = state(direct_blockers=[])
    assert result["dependency_state"]["state"] == "clear"
    assert result["blocker_state"] is None
    assert result["active_queue_eligible"] is None
    assert any(reason["code"] == "blocker_policy_unavailable" for reason in result["reasons"])
