"""Focused Bot Hook authority tests for the owning service."""

from types import SimpleNamespace
import pytest
from langboard_shared.ai import BotScopeHelper
from langboard_shared.domain.models import Bot, Project
from langboard_shared.domain.models.bases import BotTriggerCondition
from langboard_shared.domain.services.factory.BotService import BotService, BotServiceError
from langboard_shared.helpers import BotHelper, InfraHelper


class FakeScopeModel:
    """Expose the minimum native Hook storage contract."""

    @staticmethod
    def get_available_conditions() -> set[BotTriggerCondition]:
        """Return events accepted by the fake card target."""

        return {BotTriggerCondition.CardMoved}

    @staticmethod
    def get_scope_column_name() -> str:
        """Return the fake target foreign-key column."""

        return "card_id"


def test_upsert_hook_rejects_target_outside_authorized_project(monkeypatch: pytest.MonkeyPatch) -> None:
    """A project role cannot be borrowed to write a Hook into another project."""

    bot = SimpleNamespace(id=1)
    target = SimpleNamespace(id=2, project_id=20)
    authorized_project = SimpleNamespace(id=10)
    target_project = SimpleNamespace(id=20)

    def get_by_id_like(model: object, value: object) -> object | None:
        if model is Bot:
            return bot
        if model is Project and value == "project-1":
            return authorized_project
        if model is Project and value == 20:
            return target_project
        return None

    monkeypatch.setattr(InfraHelper, "get_by_id_like", get_by_id_like)
    monkeypatch.setattr(
        BotHelper,
        "get_target_model_by_param",
        lambda kind, table, uid: (FakeScopeModel, target),
    )
    writes: list[object] = []
    monkeypatch.setattr(BotScopeHelper, "upsert_conditions", lambda *args, **kwargs: writes.append(args))

    with pytest.raises(BotServiceError, match="outside the authorized project") as caught:
        BotService.upsert_hook(
            object.__new__(BotService),
            "bot-1",
            "card",
            "card-1",
            [BotTriggerCondition.CardMoved],
            project="project-1",
        )

    assert caught.value.code == "project_mismatch"
    assert writes == []
