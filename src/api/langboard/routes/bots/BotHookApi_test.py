"""Canonical REST and MCP Bot Hook contract tests."""

import json
from types import SimpleNamespace
import pytest
from langboard.mcp_tools import BotMcp
from langboard.routes.bots import BotHookApi
from langboard.routes.bots.forms import UpsertBotHookForm
from langboard_shared.domain.models.bases import BotTriggerCondition


def test_rest_and_mcp_return_same_upsert_receipt() -> None:
    """Both public adapters expose the same Hook operation receipt."""

    hook = {
        "uid": "hook-1",
        "bot_uid": "bot-1",
        "target": {"type": "card", "uid": "card-1"},
        "events": [BotTriggerCondition.CardMoved.value],
        "active": True,
    }
    calls: list[dict[str, object]] = []

    def upsert_hook(*args: object, **kwargs: object) -> dict[str, object]:
        calls.append({"args": args, **kwargs})
        return hook

    service = SimpleNamespace(bot=SimpleNamespace(upsert_hook=upsert_hook))
    actor = SimpleNamespace()
    form = UpsertBotHookForm(
        target_table="card",
        target_uid="card-1",
        events=[BotTriggerCondition.CardMoved],
        active=True,
    )

    rest_response = BotHookApi.upsert_project_bot_hook("project-1", "bot-1", form, actor, service)
    rest_receipt = json.loads(rest_response.body)["receipt"]
    mcp_receipt = BotMcp.upsert_bot_hook(
        "project-1",
        "bot-1",
        "card",
        "card-1",
        [BotTriggerCondition.CardMoved],
        True,
        actor,
        service,
    )

    assert rest_receipt == mcp_receipt == {"operation": "upserted", "hook": hook}
    assert [call["project"] for call in calls] == ["project-1", "project-1"]


def test_rest_and_mcp_reject_cross_bot_authorship(monkeypatch: pytest.MonkeyPatch) -> None:
    """An authenticated Bot cannot select another Bot as the mutation author."""

    class FakeBot:
        """Minimal authenticated Bot identity."""

        def get_uid(self) -> str:
            """Return the authenticated Bot UID."""

            return "bot-authenticated"

    actor = FakeBot()
    monkeypatch.setattr(BotHookApi, "Bot", FakeBot)
    monkeypatch.setattr(BotMcp, "Bot", FakeBot)

    with pytest.raises(Exception) as rest_error:
        BotHookApi._ensure_bot_author(actor, "bot-forged", service=SimpleNamespace())
    with pytest.raises(ValueError, match="bot_actor_mismatch"):
        BotMcp._ensure_bot_author(actor, "bot-forged")

    assert getattr(rest_error.value, "status_code", None) == 403

    with pytest.raises(Exception) as unscoped_error:
        BotHookApi._ensure_bot_author(
            actor,
            "bot-authenticated",
            project_uid="project-1",
            service=SimpleNamespace(bot=SimpleNamespace(has_project_access=lambda *_: False)),
        )
    assert getattr(unscoped_error.value, "status_code", None) == 403


def test_mcp_normalizes_raw_event_values_and_rejects_unknown_events() -> None:
    """The REST MCP executor cannot bypass Hook event validation with raw JSON."""

    assert BotMcp._normalize_hook_events([BotTriggerCondition.CardMoved.value]) == [BotTriggerCondition.CardMoved]
    with pytest.raises(ValueError, match="events_invalid"):
        BotMcp._normalize_hook_events(["unknown_event"])
    with pytest.raises(ValueError, match="active_invalid"):
        BotMcp._normalize_hook_active("false")  # type: ignore[arg-type]
