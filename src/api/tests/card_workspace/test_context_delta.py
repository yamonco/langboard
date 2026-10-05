from copy import deepcopy
import pytest
from langboard.card_workspace.application.context_delta import card_context_delta


def snapshot():
    return {
        "card_uid": "card",
        "card": {
            "core": {
                "uid": "card",
                "last_change_seq": 7,
                "description": {"content": "Body", "revision": "description-revision", "next_cursor": None},
                "linked_wikis": [{"wiki_uid": "wiki", "title": "Private"}],
            },
            "workflow": {"project_column_uid": "ready", "archived_at": None},
            "work_state": {
                "dependency_state": {"direct_blockers": []},
                "verification_state": "verified",
                "verification": {"uid": "receipt", "evidence": [{"uid": "proof"}]},
                "execution_state": {"generation": 1, "source_revision": "code-rev"},
            },
            "comments": {"items": [{"uid": "comment", "content": "hello"}], "next_cursor": None},
            "classification": {
                "relationships": {"items": [{"uid": "edge"}], "next_cursor": None},
                "labels": {"items": [], "next_cursor": None},
            },
            "checklists": {
                "items": [{"uid": "list", "checkitems": [{"uid": "item", "is_checked": False}]}],
                "next_cursor": None,
            },
        },
    }


def read(bundle, cursor=None, **overrides):
    args = dict(project_uid="project", actor_uid="actor", profile="full", key="fixture-key", cursor=cursor)
    args.update(overrides)
    return card_context_delta(bundle, **args)


def test_initial_and_unchanged_context_are_distinct_from_description_revision():
    bundle = snapshot()
    initial = read(bundle)
    assert initial.requires_full_refresh and initial.current_context_cursor
    assert "Body" not in initial.current_context_cursor
    assert initial.description_revision == "description-revision"
    unchanged = read(bundle, initial.current_context_cursor)
    assert unchanged.sections == {} and unchanged.changed_sections == []
    assert not unchanged.requires_full_refresh
    assert unchanged.card_change_seq == 7


@pytest.mark.parametrize(
    "change",
    [
        "comment",
        "blocker_add",
        "blocker_remove",
        "item_complete",
        "relation_delete",
        "item_delete",
        "wiki_revoke",
        "wiki_revision",
        "evidence_stale",
        "archive",
        "move",
        "generation",
    ],
)
def test_changes_replace_only_affected_sections_and_report_removal(change):
    before = snapshot()
    if change == "blocker_remove":
        before["card"]["work_state"]["dependency_state"]["direct_blockers"] = [{"uid": "block"}]
    cursor = read(before).current_context_cursor
    after = deepcopy(before)
    card = after["card"]
    expected = None
    if change == "comment":
        card["comments"]["items"].append({"uid": "new", "content": "new"})
        expected = "comments"
    elif change in {"blocker_add", "blocker_remove"}:
        card["work_state"]["dependency_state"]["direct_blockers"] = (
            [] if change == "blocker_remove" else [{"uid": "block"}]
        )
        expected = "work_state"
    elif change in {"item_complete", "item_delete"}:
        items = card["checklists"]["items"][0]["checkitems"]
        if change == "item_delete":
            items.clear()
        else:
            items[0]["is_checked"] = True
        expected = "checklists"
    elif change == "relation_delete":
        card["classification"]["relationships"]["items"].clear()
        expected = "classification.relationships"
    elif change == "wiki_revoke":
        card["core"]["linked_wikis"].clear()
        expected = "linked_wikis"
    elif change == "wiki_revision":
        card["core"]["linked_wikis"][0]["revision"] = "new-revision"
        expected = "linked_wikis"
    elif change == "evidence_stale":
        card["work_state"]["verification_state"] = "stale"
        expected = "work_state"
    elif change == "generation":
        card["work_state"]["execution_state"]["generation"] = 2
        expected = "work_state"
    elif change == "archive":
        card["workflow"]["archived_at"] = "2026-10-05T00:00:00Z"
        expected = "workflow"
    else:
        card["workflow"]["project_column_uid"] = "closed"
        expected = "workflow"
    delta = read(after, cursor)
    assert expected in delta.changed_sections
    assert "description" not in delta.changed_sections or change == "wiki_revoke"
    assert delta.blocker_changed == (change in {"blocker_add", "blocker_remove"})
    assert delta.permissions_changed == (change == "wiki_revoke")
    assert delta.requires_full_refresh == (change == "wiki_revoke")
    if change == "relation_delete":
        assert "classification.relationships:edge" in delta.removed_refs
    if change == "item_delete":
        assert "checklists:item" in delta.removed_refs
    if change == "wiki_revoke":
        assert "linked_wikis:wiki" in delta.removed_refs
    if change in {"evidence_stale", "generation", "wiki_revoke", "wiki_revision"}:
        assert delta.invalidated_evidence == ["evidence:proof"]
    if change == "generation":
        assert delta.execution_generation == 2 and delta.source_revision == "code-rev"


@pytest.mark.parametrize(
    "binding", [{"actor_uid": "other"}, {"project_uid": "other"}, {"profile": "execute"}, {"key": "rotated"}]
)
def test_cursor_cannot_cross_identity_project_profile_or_signing_key(binding):
    bundle = snapshot()
    delta = read(bundle, read(bundle).current_context_cursor, **binding)
    assert delta.requires_full_refresh and "invalid_or_mismatched_cursor" in delta.reasons


def test_truncated_projection_never_advances_incremental_cursor():
    before = snapshot()
    cursor = read(before).current_context_cursor
    before["card"]["comments"]["next_cursor"] = "more"
    delta = read(before, cursor)
    assert delta.requires_full_refresh and delta.current_context_cursor is None
    assert delta.removed_refs == []


def test_malformed_and_tampered_cursor_fail_to_full_refresh():
    bundle = snapshot()
    cursor = read(bundle).current_context_cursor
    for broken in ("not-json", cursor[:-1] + "x", "x" * 65537):
        assert read(bundle, broken).requires_full_refresh
