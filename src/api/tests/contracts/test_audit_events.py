import os


os.environ.setdefault("PROJECT_NAME", "langboard")

from datetime import datetime, timezone  # noqa: E402
import pytest  # noqa: E402
from langboard_shared.domain.contracts.audit_events import (  # noqa: E402
    REDACTED,
    AuditAction,
    AuditEvent,
    diff_payload,
    serialize_events,
)


UTC = timezone.utc
BASE = datetime(2026, 9, 19, 14, 0, 0, tzinfo=UTC)


def event(**overrides) -> AuditEvent:
    defaults = dict(
        event_uid="evt-1",
        action=AuditAction.ORGANIZATION_SUSPENDED,
        actor_uid="user-1",
        organization_uid="org-1",
        resource_type="organization",
        resource_uid="org-1",
        result="success",
        recorded_at=BASE,
    )
    defaults.update(overrides)
    return AuditEvent(**defaults)


class TestAuditEvent:
    def test_valid_event_payload(self):
        payload = event().to_payload()
        assert payload["action"] == "organization.suspended"
        assert payload["resource"] == {"type": "organization", "uid": "org-1"}

    def test_rejects_bad_result(self):
        with pytest.raises(ValueError):
            event(result="maybe")

    def test_rejects_naive_timestamp(self):
        with pytest.raises(ValueError):
            event(recorded_at=datetime(2026, 9, 19))

    def test_rejects_missing_actor(self):
        with pytest.raises(ValueError):
            event(actor_uid="")


class TestRedaction:
    def test_masks_sensitive_keys(self):
        audited = event(before={"password": "hunter2", "title": "ok"}, after={"api_token": "x", "title": "ok"})
        payload = audited.to_payload()
        assert payload["before"]["password"] == REDACTED
        assert payload["before"]["title"] == "ok"
        assert payload["after"]["api_token"] == REDACTED

    def test_masks_nested_dicts(self):
        audited = event(after={"settings": {"client_secret": "s3cr3t"}})
        assert audited.to_payload()["after"]["settings"]["client_secret"] == REDACTED


class TestDiffPayload:
    def test_only_changed_keys(self):
        changes = diff_payload({"a": 1, "b": 2}, {"a": 1, "b": 3, "c": 4})
        assert changes == {"b": {"before": 2, "after": 3}, "c": {"before": None, "after": 4}}

    def test_identical_payload_empty(self):
        assert diff_payload({"a": 1}, {"a": 1}) == {}


class TestSerializeEvents:
    def test_json_round_trip_keeps_redaction(self):
        import json

        audited = event(before={"token": "abc"})
        restored = json.loads(serialize_events([audited]))
        assert restored[0]["before"]["token"] == REDACTED
        assert restored[0]["event_uid"] == "evt-1"
