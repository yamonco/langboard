"""Native evidence endpoint keeps identity and stale conflicts on the server."""

import json
from types import SimpleNamespace
from unittest.mock import Mock
import pytest
from langboard.routes.board.BoardOrchestrationApi import (
    RecordVerificationEvidenceForm,
    record_verification_evidence,
)
from langboard_shared.core.routing import ApiException
from langboard_shared.core.types import SnowflakeID
from langboard_shared.domain.models import User
from langboard_shared.domain.services.CardVerification import VerificationConflict
from pydantic import SecretStr


def form():
    return RecordVerificationEvidenceForm.model_validate(
        {
            "expected_change_seq": 9,
            "decision": "partial",
            "evidence": [{"reference": "run:1", "source_revision": "commit", "environment": "canary"}],
        }
    )


def reviewer():
    return User(
        id=SnowflakeID(7),
        firstname="Test",
        lastname="Reviewer",
        email="reviewer@example.invalid",
        password=SecretStr("unused"),
    )


def test_endpoint_passes_authenticated_actor_and_returns_current_receipt():
    update = Mock(return_value={"uid": "record", "decision": "partial"})
    response = record_verification_evidence(
        "project",
        "card",
        form(),
        user_or_bot=reviewer(),
        service=SimpleNamespace(card=SimpleNamespace(record_verification_evidence=update)),
    )
    actor, project, card, submission = update.call_args.args
    assert actor.id == 7 and (project, card) == ("project", "card")
    assert submission.expected_change_seq == 9
    assert json.loads(response.body)["verification"]["uid"] == "record"


def test_endpoint_exposes_stale_card_or_previous_record_as_conflict():
    update = Mock(side_effect=VerificationConflict("stale"))
    with pytest.raises(ApiException.Conflict_409) as error:
        record_verification_evidence(
            "project",
            "card",
            form(),
            user_or_bot=reviewer(),
            service=SimpleNamespace(card=SimpleNamespace(record_verification_evidence=update)),
        )
    assert error.value.status_code == 409
