from contextlib import contextmanager
from importlib import import_module
from types import SimpleNamespace
from unittest.mock import Mock
import pytest
from pydantic import SecretStr
from ....core.types import SnowflakeID
from ...models import User
from ..CardVerification import VerificationConflict, VerificationSubmission
from .CardService import CardService


def setup_service(monkeypatch, *, seq=9, latest=None, checked=True, archived=False):
    project = SimpleNamespace(id=1)
    card = SimpleNamespace(id=2, deleted_at=None, archived_at=archived, is_linked_resource=False, last_change_seq=seq)
    item = SimpleNamespace(get_uid=lambda: "item", is_checked=checked)
    db = SimpleNamespace(
        exec=Mock(side_effect=[SimpleNamespace(first=lambda: card), SimpleNamespace(all=lambda: [item])]), insert=Mock()
    )
    module = import_module(CardService.__module__)
    monkeypatch.setattr(module.InfraHelper, "get_records_with_foreign_by_params", lambda *_: (project, card))

    @contextmanager
    def atomic():
        yield db

    monkeypatch.setattr(module.DbSession, "atomic", atomic)
    latest_read = Mock(return_value={2: latest} if latest else {})
    service = CardService(
        lambda _: None,
        lambda _: None,
        SimpleNamespace(
            card_verification=SimpleNamespace(get_latest_by_card_ids=latest_read),
        ),
    )
    service.get_work_states = Mock(return_value={2: {"verification_state": "verified"}})
    monkeypatch.setattr(module.CardPublisher, "updated", Mock())
    return service, db


def request(**changes):
    proof = {"reference": "run:1", "source_revision": "commit", "environment": "canary"}
    return VerificationSubmission.model_validate(
        {
            "expected_change_seq": 9,
            "decision": "verified",
            "required_checkitem_uids": ["item"],
            "evidence": [proof, {**proof, "checkitem_uid": "item"}],
            **changes,
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


def test_evidence_appends_authenticated_reviewer_and_never_mutates_card(monkeypatch):
    service, db = setup_service(monkeypatch)
    # Native insertion allocates ID; this mock supplies one for the receipt.
    db.insert.side_effect = lambda record: setattr(record, "id", SnowflakeID(11))
    result = service.record_verification_evidence(reviewer(), "project", "card", request())
    inserted = db.insert.call_args.args[0]
    assert int(inserted.recorded_by_user_id) == 7
    assert inserted.recorded_by_bot_id is None
    assert inserted.source_change_seq == 9
    assert result["decision"] == "verified"
    published = import_module(CardService.__module__).CardPublisher.updated.call_args.args
    assert published[0].id == 1 and published[1].id == 2
    assert published[2:] == (None, {"work_state": {"verification_state": "verified"}})
    assert "FOR UPDATE" in str(db.exec.call_args_list[0].args[0])
    assert len(db.exec.call_args_list) == 2


@pytest.mark.parametrize("changes", [{"seq": 10}, {"latest": SimpleNamespace(get_uid=lambda: "newer-record")}])
def test_stale_card_or_record_fence_does_not_write(monkeypatch, changes):
    service, db = setup_service(monkeypatch, **changes)
    with pytest.raises(VerificationConflict):
        service.record_verification_evidence(reviewer(), "project", "card", request())
    db.insert.assert_not_called()


@pytest.mark.parametrize(
    "submission_changes,setup_changes",
    [
        ({}, {"checked": False}),
        (
            {
                "required_checkitem_uids": [],
                "evidence": [
                    {"reference": "run:1", "source_revision": "a", "environment": "canary", "checkitem_uid": "foreign"}
                ],
            },
            {},
        ),
    ],
)
def test_incomplete_or_foreign_acceptance_never_writes(monkeypatch, submission_changes, setup_changes):
    service, db = setup_service(monkeypatch, **setup_changes)
    decision = request(**{**submission_changes, "decision": "partial" if submission_changes else "verified"})
    with pytest.raises(ValueError):
        service.record_verification_evidence(reviewer(), "project", "card", decision)
    db.insert.assert_not_called()


def test_archived_card_cannot_receive_active_verification(monkeypatch):
    service, db = setup_service(monkeypatch, archived=True)
    assert service.record_verification_evidence(reviewer(), "project", "card", request()) is None
    db.insert.assert_not_called()
