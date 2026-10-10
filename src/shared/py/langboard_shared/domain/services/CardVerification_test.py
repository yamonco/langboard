import pytest
from pydantic import ValidationError
from .CardVerification import VerificationSubmission
from .CardWorkState import project_work_state


def submission(**changes):
    return VerificationSubmission.model_validate({
        "expected_change_seq": 9, "decision": "verified",
        "evidence": [{"reference": "https://example.invalid/run/1", "source_revision": "commit-one", "environment": "canary"}],
        **changes,
    })


@pytest.mark.parametrize("field", ["reference", "source_revision", "environment"])
def test_evidence_requires_reference_revision_and_environment(field):
    proof = {"reference": "run:1", "source_revision": "commit", "environment": "canary"}
    proof[field] = " "
    with pytest.raises(ValidationError):
        submission(evidence=[proof])


def test_verified_requires_explicit_card_and_required_item_evidence():
    with pytest.raises(ValidationError):
        submission(required_checkitem_uids=["item"])
    with pytest.raises(ValidationError):
        submission(evidence=[{"reference": "run:1", "source_revision": "a", "environment": "canary", "checkitem_uid": "item"}])
    proof = submission().evidence[0].model_dump()
    assert submission(required_checkitem_uids=["item"], evidence=[proof, {**proof, "checkitem_uid": "item"}])


def test_client_cannot_forge_reviewer_or_duplicate_acceptance():
    with pytest.raises(ValidationError):
        submission(recorded_by_user_id=1)
    with pytest.raises(ValidationError):
        submission(required_checkitem_uids=["item", "item"])


def test_current_evidence_and_stale_evidence_are_independent_of_column_and_checkmarks():
    facts = {"card_uid": "card", "workflow_stage": "review", "archived": False, "linked_resource": False,
             "total": 0, "completed": 0, "started": 0, "paused": 0, "change_seq": 9}
    record = {"uid": "record", "source_change_seq": 9, "decision": "verified", "evidence": []}
    assert project_work_state(**facts)["verification_state"] == "unverified"
    current = project_work_state(**facts, verification_record=record)
    assert current["verification_state"] == "verified"
    assert current["blocker_state"] is None
    stale = project_work_state(**{**facts, "change_seq": 10}, verification_record=record)
    assert stale["verification_state"] == "stale"
    assert stale["verification"]["uid"] == "record"
    # Workflow movement cannot make obsolete evidence current again.
    assert project_work_state(**{**facts, "workflow_stage": "closed", "change_seq": 10}, verification_record=record)["verification_state"] == "stale"
