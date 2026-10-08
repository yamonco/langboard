# ruff: noqa: F811
"""Native issue observation consumption; resolution never grants reviewer approval."""

import pytest
from langboard.apps.CardSignal import bind_check, read_checks, unlink_check
from langboard.apps.GitHubManifest import GitHubManifestUnavailable
from langboard.apps.SignalInbox import list_board_signals
from langboard_shared.core.db import DbSession, SqlBuilder
from langboard_shared.core.db.DbEngine import DbEngine
from langboard_shared.domain.models import AppSignal, Card, CardAppSignalBinding, Organization
from langboard_shared.domain.services import DomainService
from langboard_shared.domain.services.AppSignalProjection import card_signal_projections
from langboard_shared.domain.services.factory.SecretReferenceService_test import secrets  # noqa: F401
from langboard_shared.domain.services.factory.WorkflowStageService_app_test import board  # noqa: F401
from langboard_shared.Env import Env
from test_glitchtip_connection import setup  # noqa: F401
from test_glitchtip_signal import refresh, selected  # noqa: F401


@pytest.fixture
def card_scope(selected, monkeypatch):
    from langboard_shared.domain.models import EmployeeMembershipPolicy, ScimGroup, ScimGroupMember, UserIdentityLink

    engine = DbEngine.get_main_engine()
    for model in (
        Organization,
        EmployeeMembershipPolicy,
        ScimGroup,
        ScimGroupMember,
        UserIdentityLink,
        Card,
        CardAppSignalBinding,
    ):
        model.__table__.create(engine, checkfirst=True)
    service, board, *_ = selected[0]
    service.card = DomainService().card
    monkeypatch.setattr(type(Env), "CARD_INTERNAL_ACCESS_MODE", property(lambda _: "project_members"))
    with DbSession.use(readonly=False) as db:
        board[4].actions = ["read", "update", "card_update"]
        db.update(board[4])
        card = Card(
            project_id=board[2].id,
            project_column_id=board[5][0].id,
            title="Observed issue",
            visibility="SHARED",
            last_change_seq=7,
        )
        db.insert(card)
    refresh(selected)
    with DbSession.use(readonly=False) as db:
        signal = db.exec(SqlBuilder.select.table(AppSignal)).first()
    return selected, card, signal


def attach(scope):
    selected, card, signal = scope
    service, board, *_ = selected[0]
    return bind_check(
        service,
        board[1],
        board[2].get_uid(),
        card.get_uid(),
        selected[1]["connection_uid"],
        selected[2]["resource_uid"],
        signal.get_uid(),
        7,
        None,
    )


def test_issue_card_consumption_resolution_and_stale(card_scope):
    selected, card, _ = card_scope
    service, board, *_ = selected[0]
    def inbox():
        return list_board_signals(service, board[1], board[2].get_uid())
    row = inbox()["items"][0]
    assert row["provider"] == "glitchtip" and row["time_basis"] == "observation" and row["can_bind_card"]
    receipt = attach(card_scope)
    assert inbox()["items"] == []
    proof = card_signal_projections([card])[card.id][0]
    assert proof["state"] == "failed" and proof["outcome"] == "unresolved" and proof["time_basis"] == "observation"
    selected[0][4]["rows"][0]["status"] = "resolved"
    refresh(selected)
    proof = read_checks(service, board[1], board[2].get_uid(), card.get_uid())["items"][0]
    assert proof["state"] == "resolved" and proof["state"] != "passed"
    selected[0][4]["rows"][0]["status"] = "unresolved"
    refresh(selected)
    assert card_signal_projections([card])[card.id][0]["state"] == "failed"
    with DbSession.use(readonly=False) as db:
        card.last_change_seq = 8
        db.update(card)
    assert card_signal_projections([card])[card.id][0]["state"] == "stale"
    unlink_check(service, board[1], board[2].get_uid(), card.get_uid(), receipt["binding_uid"], receipt["revision"])
    assert len(inbox()["items"]) == 1


@pytest.mark.parametrize("failure", ["role", "resource", "secret", "capability", "connection", "resources_capability"])
def test_glitchtip_current_authority_blocks_card_consumption(card_scope, failure):
    from test_glitchtip_signal import mutate

    selected, card, _ = card_scope
    attach(card_scope)
    if failure == "resources_capability":
        from langboard_shared.domain.models import BoardAppBinding

        with DbSession.use(readonly=False) as db:
            binding = db.exec(SqlBuilder.select.table(BoardAppBinding)).first()
            binding.granted_capabilities = ["signals.read"]
            db.update(binding)
    else:
        mutate(selected, failure)
    assert card_signal_projections([card]) == {}
    with pytest.raises(GitHubManifestUnavailable):
        attach(card_scope)


def test_glitchtip_work_state_observation_never_verifies_or_closes():
    from langboard_shared.domain.services.CardWorkState import project_work_state

    common = dict(
        card_uid="card",
        workflow_stage=None,
        archived=False,
        linked_resource=False,
        total=1,
        completed=0,
        started=0,
        paused=0,
        change_seq=7,
    )
    for state in ("failed", "resolved", "ignored", "stale"):
        result = project_work_state(
            **common, external_signals=[dict(provider="glitchtip", state=state, binding_uid="binding")]
        )
        assert result["verification_state"] == "unverified" and result["completed"] is None
        assert result["external_execution_state"] is None
        assert any(r["code"] == "external_issue_observation_" + state for r in result["reasons"])
        assert (result["blocker_state"] == "blocked") == (state == "failed")
