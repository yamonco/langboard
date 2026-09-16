"""Bot Hook REST and MCP adapter contract tests."""

import json
from inspect import signature
from types import SimpleNamespace
import pytest
from langboard.mcp_tools import BotMcp
from langboard.routes.bots import BotHookApi
from langboard.routes.bots.forms import CreateBotScopeForm, UpsertBotHookForm
from langboard_shared.domain.models.bases import BotTriggerCondition
from pydantic import ValidationError


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


def test_compatibility_hook_authorizes_the_resolved_target_project(monkeypatch: pytest.MonkeyPatch) -> None:
    """The legacy route cannot rely on a project path parameter that it does not have."""

    class FakeUser:
        is_admin = False
        email = "member@example.com"

    actor = FakeUser()
    project = SimpleNamespace(get_uid=lambda: "project-1")
    calls: list[dict[str, object]] = []
    service = SimpleNamespace(
        bot=SimpleNamespace(
            get_hook_target_project=lambda *_: project,
            upsert_hook=lambda *args, **kwargs: calls.append({"args": args, **kwargs}) or {"uid": "hook-1"},
        ),
        project=SimpleNamespace(get_user_role_actions_by_project=lambda *_: ["update"]),
    )
    monkeypatch.setattr(BotHookApi, "User", FakeUser)
    form = UpsertBotHookForm(
        target_table="card",
        target_uid="card-1",
        events=[BotTriggerCondition.CardMoved],
    )

    response = BotHookApi.upsert_bot_hook("bot-1", form, actor, service)

    assert json.loads(response.body) == {"hook": {"uid": "hook-1"}}
    assert calls[0]["project"] == "project-1"


def test_compatibility_hook_rejects_users_without_project_update(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeUser:
        is_admin = False
        email = "reader@example.com"

    actor = FakeUser()
    project = SimpleNamespace(get_uid=lambda: "project-1")
    service = SimpleNamespace(
        bot=SimpleNamespace(get_hook_target_project=lambda *_: project),
        project=SimpleNamespace(get_user_role_actions_by_project=lambda *_: ["read"]),
    )
    monkeypatch.setattr(BotHookApi, "User", FakeUser)
    form = UpsertBotHookForm(
        target_table="card",
        target_uid="card-1",
        events=[BotTriggerCondition.CardMoved],
    )

    with pytest.raises(Exception) as error:
        BotHookApi.upsert_bot_hook("bot-1", form, actor, service)

    assert getattr(error.value, "status_code", None) == 403


def test_bot_hook_event_input_is_bounded() -> None:
    with pytest.raises(ValidationError):
        UpsertBotHookForm(
            target_table="card",
            target_uid="card-1",
            events=[BotTriggerCondition.CardMoved] * (len(BotTriggerCondition) + 1),
        )


def test_form_model_exposes_default_factory_values_to_fastapi() -> None:
    conditions = signature(CreateBotScopeForm.from_form).parameters["conditions"]

    assert conditions.default.default == []


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
