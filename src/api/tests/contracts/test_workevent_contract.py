import os
from datetime import datetime, timezone


os.environ.setdefault("PROJECT_NAME", "langboard")

from langboard_shared.domain.contracts import (  # noqa: E402
    WorkEvent,
    WorkEventActor,
    WorkEventEnvelope,
    WorkEventFilter,
    WorkEventScope,
    WorkEventType,
)


def make_event(event_type: WorkEventType = WorkEventType.CARD_ASSIGNED) -> WorkEvent:
    return WorkEvent(
        event_id="evt-001",
        event_type=event_type,
        actor=WorkEventActor(principal_type="user", principal_id="u1", display_name="Test User"),
        scope_type=WorkEventScope.CARD,
        scope_id="card-001",
        project_uid="proj-001",
        occurred_at=datetime(2026, 9, 18, 12, 0, 0, tzinfo=timezone.utc),
        payload={"card_title": "Test"},
        payload_hash="abc123",
        correlation_id="corr-001",
    )


def test_envelope_serializes_all_required_fields() -> None:
    envelope = WorkEventEnvelope(event=make_event())
    d = envelope.to_dict()
    assert d["spec_version"] == "1.0"
    assert d["source"] == "langboard"
    assert d["event_id"] == "evt-001"
    assert d["event_type"] == "card.assigned"
    assert d["actor"]["principal_type"] == "user"
    assert d["scope"]["type"] == "card"
    assert d["scope"]["project_uid"] == "proj-001"
    assert "occurred_at" in d
    assert d["payload_hash"] == "abc123"
    assert d["correlation_id"] == "corr-001"


def test_envelope_handles_empty_event() -> None:
    envelope = WorkEventEnvelope()
    d = envelope.to_dict()
    assert d == {"spec_version": "1.0", "source": "langboard"}


def test_event_id_is_stable_for_idempotent_retries() -> None:
    e = make_event()
    assert e.event_id == "evt-001"
    e2 = make_event()
    assert e2.event_id == "evt-001"


def test_filter_excludes_low_value_events() -> None:
    for excluded in ("comment.reacted", "card.viewed", "card.moved"):
        assert WorkEventFilter.should_emit(excluded) is False


def test_filter_includes_action_required_events() -> None:
    for included in ("card.assigned", "card.mentioned", "card.approval_requested"):
        assert WorkEventFilter.should_emit(included) is True


def test_action_required_types_are_priority() -> None:
    types = WorkEventFilter.action_required_types()
    assert len(types) >= 9
    assert WorkEventType.CARD_ASSIGNED in types
    assert WorkEventType.ONBOARDING_FAILED in types
