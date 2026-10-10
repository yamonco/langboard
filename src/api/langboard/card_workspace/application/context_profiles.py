"""Purpose-specific native section selection; unknown contracts remain explicit."""

from dataclasses import replace
from typing import Literal
from ..domain import CardBundleInclude
from .ports import CardBundleSource


ContextProfile = Literal["execute", "review", "triage", "full"]
PROFILE_SECTIONS = {
    "execute": [CardBundleInclude.Description, CardBundleInclude.Checklists],
    "review": [CardBundleInclude.Checklists],
    "triage": [CardBundleInclude.Description, CardBundleInclude.Classification],
    "full": list(CardBundleInclude),
}


def select_profile_sections(profile: ContextProfile | None, include: list[CardBundleInclude] | None):
    if profile is None:
        return include
    if profile not in PROFILE_SECTIONS:
        raise ValueError("Unknown context profile")
    return list(dict.fromkeys([*PROFILE_SECTIONS[profile], *(include or [])]))


def profile_source(source: CardBundleSource, profile: ContextProfile | None) -> CardBundleSource:
    """Filter before pagination so completed history cannot hide open acceptance."""
    if profile != "execute":
        return source
    checklists = []
    for checklist in source.checklists:
        all_items = checklist.get("checkitems", [])
        open_items = [item for item in all_items if item.get("is_checked") is not True]
        if open_items:
            checklists.append({**checklist, "checkitems": open_items})
    return replace(source, checklists=checklists)


def profile_context(profile: ContextProfile, source: CardBundleSource, selected: list[CardBundleInclude]):
    """Expose availability without inventing execution goals, approvals or summaries."""
    state = source.details.get("work_state") or {}
    verification = state.get("verification")
    current = state.get("verification_state") != "stale" and verification is not None
    context = {
        "profile": profile,
        "omitted_sections": [
            {"section": section.value, "reason": "profile_not_selected"}
            for section in CardBundleInclude
            if section not in selected
        ],
        "unavailable_fields": [
            {"field": name, "reason": "native_projection_unavailable"}
            for name in ("execution_contract", "next_action", "input_refs")
        ],
        "direct_blockers": state.get("dependency_state", {}).get("direct_blockers"),
        "current_verification": verification if current else None,
        "verification_state": state.get("verification_state"),
        "source_change_seq": state.get("verification_source_change_seq"),
        "approval": "not_granted_by_read",
    }
    context["omitted_sections"].extend(source.omitted_sections)
    if profile == "execute":
        context["checklist_policy"] = "unchecked_only"
        context["omitted_completed_checkitems"] = {
            "count": state.get("checklist_progress", {}).get("completed"),
            "reason": "completed_history_not_selected",
        }
    if profile == "triage":
        context["unavailable_fields"] += [
            {"field": name, "reason": "requires_explicit_project_search_or_review"}
            for name in ("candidate_cards", "differences", "proposed_decision")
        ]
    return context


def profile_continuations(bundle: dict) -> list[dict[str, str]]:
    """Make every bounded projection explicit before a caller acts on partial context."""
    pending = []

    def visit(value, path):
        if isinstance(value, dict):
            for key, child in value.items():
                if key.endswith("next_cursor") and isinstance(child, str) and child:
                    pending.append({"section": path, "cursor": child})
                elif isinstance(child, (dict, list)):
                    visit(child, f"{path}.{key}" if path else key)
        elif isinstance(value, list):
            for index, child in enumerate(value):
                visit(child, f"{path}[{index}]")

    visit(bundle, "")
    return pending
