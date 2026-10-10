import pytest
from .CardWorkState import project_work_state


def state(**changes):
    stage = changes.get("workflow_stage")
    if stage in {"backlog", "ready", "active", "review", "closed", "reference"}:
        changes.setdefault(
            "workflow_policy",
            {
                "key": stage,
                "counts_as_completed": stage == "closed",
                "active_queue_policy": "exclude" if stage in {"closed", "reference"} else "conditional",
                "overdue_policy": "suppress" if stage == "closed" else "normal",
            },
        )
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


@pytest.mark.parametrize("stage", ["released", "closed"])
def test_registry_completion_is_independent_of_verification_and_unchecked_items(stage):
    policy = {"key": stage, "counts_as_completed": True, "active_queue_policy": "exclude", "overdue_policy": "suppress"}
    result = state(workflow_stage=stage, workflow_policy=policy, total=3, completed=1)
    assert result["workflow_stage"] == stage
    assert result["completed"] is True
    assert result["verification_state"] == "partial"
    assert result["active_queue_eligible"] is False
    assert result["overdue_suppressed"] is True
    assert result["state_inconsistency"][0]["code"] == "closed_with_open_checkitems"


def test_registry_policy_change_reinterprets_closed_without_guessing_or_approval():
    policy = {
        "key": "closed",
        "counts_as_completed": False,
        "active_queue_policy": "include",
        "overdue_policy": "normal",
    }
    result = state(workflow_stage="closed", workflow_policy=policy)
    assert result["completed"] is False
    assert result["overdue_suppressed"] is False
    assert result["active_queue_eligible"] is None  # Input/approval gates remain unknown.
    assert result["verification_state"] == "unverified"
    policy["active_queue_policy"] = "exclude"
    assert state(workflow_stage="closed", workflow_policy=policy)["active_queue_eligible"] is False


def test_foreign_policy_cannot_classify_unknown_key():
    policy = {
        "key": "released",
        "counts_as_completed": True,
        "active_queue_policy": "exclude",
        "overdue_policy": "suppress",
    }
    result = state(workflow_stage="Other", workflow_policy=policy)
    assert result["workflow_stage"] is None and result["completed"] is None
    assert result["active_queue_eligible"] is None


def test_missing_registry_policy_stays_unknown_even_for_former_builtin_key():
    result = state(workflow_stage="closed", workflow_policy=None)
    assert result["completed"] is None
    assert result["active_queue_policy"] is None
    assert result["overdue_suppressed"] is None
    assert result["active_queue_eligible"] is None
    assert any(reason["code"] == "workflow_policy_unavailable" for reason in result["reasons"])
