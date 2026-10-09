# ruff: noqa: F811
"""An independently declared adapter shares native card scope and revocation gates."""

import importlib
import pytest
from langboard.apps.CardSignal import authorized_signal_scope
from langboard.apps.GitHubManifest import GitHubManifestUnavailable
from langboard_shared.core.db import DbSession, SqlBuilder
from langboard_shared.domain.models import AppSignal, BoardAppBinding
from langboard_shared.domain.services.AppManifest import AppManifest, AppSignalPolicy
from test_card_signal_projection import scoped  # noqa: F401
from test_github_signal import board, installation, lifecycle, secrets, send, signal_storage  # noqa: F401


@pytest.mark.parametrize("revoke", [None, "resource", "capability", "connection"])
def test_independent_adapter_scope_and_revocation(scoped, monkeypatch, revoke):
    state, _, _, _ = scoped
    send(state)
    adapter = AppManifest(
        "independent-monitor", "Independent Monitor", ("service",), ("signals.read",),
        signal_policy=AppSignalPolicy(("incident.observed",), ("service",)),
    )
    manifests = importlib.import_module("langboard_shared.domain.services.AppManifest")
    card_scope = importlib.import_module("langboard.apps.CardSignal")
    registry = {**manifests.APP_MANIFESTS, adapter.key: adapter}
    monkeypatch.setattr(manifests, "APP_MANIFESTS", registry)
    monkeypatch.setattr(card_scope, "APP_MANIFESTS", registry)
    with DbSession.atomic() as db:
        state[2].app_key = adapter.key
        state[4].resource_type = "service"
        if revoke == "connection":
            state[2].state = "disconnected"
        if revoke == "resource":
            state[4].is_selected = False
        for row in (state[2], state[4]):
            db.update(row)
        binding = db.exec(SqlBuilder.select.table(BoardAppBinding).where(BoardAppBinding.id == state[4].board_binding_id)).first()
        binding.app_key = adapter.key
        if revoke == "capability":
            binding.granted_capabilities = []
        db.update(binding)
        signal = db.exec(SqlBuilder.select.table(AppSignal).where(AppSignal.resource_id == state[4].id)).first()
        signal.provider = adapter.key
        signal.event_type = "incident.observed"
        signal.commit_sha = ""
        db.update(signal)
        args = (state[0], db, state[1][1], state[1][2].get_uid(), state[2].get_uid(), state[4].get_uid(), signal.get_uid())
        if revoke:
            with pytest.raises(GitHubManifestUnavailable):
                authorized_signal_scope(*args)
        else:
            result = authorized_signal_scope(*args)
            assert result[0].id == signal.id and result[2].id == state[4].id
