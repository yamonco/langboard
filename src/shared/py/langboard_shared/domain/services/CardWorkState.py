"""One read-only work-state projection; missing evidence stays explicit.

Column names, checklist completion and legacy ``passed`` records are never
approval evidence. This first contract exposes unknown blocker/agent state
instead of silently making those cards executable.
"""

from typing import Any


WORKFLOW_STAGES = frozenset({"backlog", "ready", "active", "review", "closed", "reference"})


def project_work_state(
    *,
    card_uid: str,
    workflow_stage: str | None,
    archived: bool,
    linked_resource: bool,
    total: int,
    completed: int,
    started: int,
    paused: int,
    change_seq: int = 0,
    verification_record: dict[str, Any] | None = None,
    direct_blockers: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Interpret native facts equally for every authorized reader.

    Progress counts are ordinary checkitems, not a required-acceptance policy.
    ``partial`` therefore means checklist progress only, never final approval.
    Null axes mean the authoritative policy/lifecycle is not yet integrated.
    """
    stage = workflow_stage if workflow_stage in WORKFLOW_STAGES else None
    reasons: list[dict[str, str]] = []
    inconsistencies: list[dict[str, str]] = []

    def reason(code: str, message: str, source: str) -> dict[str, str]:
        return {"code": code, "message": message, "source_ref": f"card:{card_uid}/{source}"}

    if stage is None:
        reasons.append(reason("workflow_unclassified", "Column has no explicit workflow mapping.", "column"))
    material = "wiki-like" if linked_resource else "reference" if stage == "reference" else "work"
    verification = "not_required" if linked_resource else "partial" if completed else "unverified"
    if not linked_resource and verification_record is not None:
        if verification_record.get("source_change_seq") != change_seq:
            verification = "stale"
            reasons.append(
                reason("verification_stale", "Card changed after the recorded verification.", "verification")
            )
        elif verification_record.get("decision") in {"verified", "partial", "unverified"}:
            verification = verification_record["decision"]
            reasons.append(
                reason(
                    "verification_recorded",
                    "Current reviewer evidence covers the explicitly declared scope; approval gates are separate.",
                    "verification",
                )
            )
    elif not linked_resource:
        reasons.append(
            reason("verification_evidence_unavailable", "Checklist progress is not approval evidence.", "verification")
        )
    if started:
        execution = "human_active"
    elif paused:
        execution = "paused"
    elif linked_resource:
        execution = "idle"
    else:
        execution = None
        reasons.append(
            reason(
                "agent_lifecycle_unavailable", "No authoritative agent lifecycle projection is available.", "execution"
            )
        )
    if direct_blockers is not None:
        for blocker in direct_blockers:
            visible = blocker.get("accessible") is True and blocker.get("card_uid") is not None
            reasons.append(
                {
                    "code": "dependency_unfinished" if visible else "dependency_unavailable",
                    "message": "Prerequisite is not closed."
                    if visible
                    else "An inaccessible prerequisite prevents execution.",
                    "source_ref": f"card:{blocker['card_uid']}" if visible else f"card:{card_uid}/blockers",
                }
            )
        if not direct_blockers:
            reasons.append(reason("dependencies_clear", "No unsatisfied blocks prerequisites.", "blockers"))
    reasons.append(
        reason(
            "blocker_policy_unavailable",
            "Input and approval gates have not been evaluated."
            if direct_blockers is not None
            else "Dependency, input and approval gates have not been evaluated.",
            "blockers",
        )
    )
    if archived:
        reasons.append(reason("archived", "Archived cards are excluded from the active queue.", "lifecycle"))
    if archived and started:
        inconsistencies.append(
            reason("archived_with_running_timer", "Archived card still has a running human timer.", "checkitems")
        )
    if stage == "closed" and total > completed:
        inconsistencies.append(
            reason(
                "closed_with_open_checkitems",
                "Closed workflow still has unchecked items; no required-acceptance policy is inferred.",
                "checkitems",
            )
        )
    if stage == "active" and total > 0 and total == completed:
        inconsistencies.append(
            reason(
                "active_with_all_checkitems_completed",
                "All checkitems are complete while workflow remains active; approval is separate.",
                "checkitems",
            )
        )
    return {
        "version": 1,
        "workflow_stage": stage,
        "verification_state": verification,
        "verification_source_change_seq": change_seq,
        "verification": verification_record,
        "execution_state": execution,
        "blocker_state": "blocked" if direct_blockers else None,
        "dependency_state": {
            "state": "blocked" if direct_blockers else "clear" if direct_blockers is not None else None,
            "direct_blockers": direct_blockers,
        },
        "material_kind": material,
        "lifecycle": "archived" if archived else "active",
        "active_queue_eligible": False
        if archived or stage in {"closed", "reference"} or linked_resource or direct_blockers
        else None,
        "checklist_progress": {"total": total, "completed": completed},
        "reasons": reasons,
        "state_inconsistency": inconsistencies,
    }
