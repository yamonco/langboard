"""Report the execution readiness verdict the database recheck gate persists."""

import os
from types import SimpleNamespace
from typing import Any
import pytest
from sqlalchemy import create_engine, text


os.environ.setdefault("PROJECT_NAME", "langboard")

from langboard_shared.core.db.DbEngine import DbEngine  # noqa: E402
from langboard.card_workspace.application.ports import CardExecutionSource  # noqa: E402
from langboard.card_workspace.infrastructure.native import NativeCardWorkspaceAdapter  # noqa: E402


CARD_ID = 101


def _service(card: Any = None) -> SimpleNamespace:
    """Resolve one project/card pair like the native services would."""

    return SimpleNamespace(
        project=SimpleNamespace(get_by_id_like=lambda _: SimpleNamespace(id=1)),
        card=SimpleNamespace(
            get_by_id_like=lambda _: card if card is not None else SimpleNamespace(id=CARD_ID, project_id=1)
        ),
    )


def _adapter_with_readiness(
    monkeypatch: pytest.MonkeyPatch,
    rows: list[dict[str, Any]],
    card: Any = None,
) -> NativeCardWorkspaceAdapter:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    with engine.begin() as connection:
        connection.execute(
            text(
                "CREATE TABLE card_execution_readiness ("
                "card_id bigint PRIMARY KEY, is_ready boolean, execution_generation integer)"
            )
        )
        for row in rows:
            connection.execute(
                text(
                    "INSERT INTO card_execution_readiness (card_id, is_ready, execution_generation) "
                    "VALUES (:card_id, :is_ready, :execution_generation)"
                ),
                row,
            )
    monkeypatch.setattr(DbEngine, "get_readonly_engine", lambda: engine)
    return NativeCardWorkspaceAdapter(object(), _service(card))


def test_ready_card_reports_the_persisted_generation(monkeypatch: pytest.MonkeyPatch) -> None:
    """A card in a ready-mapped column with terminal prerequisites is persisted ready."""

    adapter = _adapter_with_readiness(
        monkeypatch,
        [{"card_id": CARD_ID, "is_ready": True, "execution_generation": 2}],
    )

    assert adapter.get_card_execution("p1", "c1") == CardExecutionSource(is_ready=True, generation=2)


def test_non_ready_card_fails_closed_with_its_last_generation(monkeypatch: pytest.MonkeyPatch) -> None:
    """A regressed card keeps its generation while is_ready returns to false."""

    adapter = _adapter_with_readiness(
        monkeypatch,
        [{"card_id": CARD_ID, "is_ready": False, "execution_generation": 1}],
    )

    assert adapter.get_card_execution("p1", "c1") == CardExecutionSource(is_ready=False, generation=1)


def test_untracked_card_is_not_ready_at_generation_zero(monkeypatch: pytest.MonkeyPatch) -> None:
    """An unmapped or unbound card has no gate row yet and stays not ready."""

    adapter = _adapter_with_readiness(monkeypatch, [])

    assert adapter.get_card_execution("p1", "c1") == CardExecutionSource(is_ready=False, generation=0)


def test_unknown_card_has_no_execution_section(monkeypatch: pytest.MonkeyPatch) -> None:
    """A card outside the project resolves to no execution section at all."""

    adapter = _adapter_with_readiness(monkeypatch, [], card=SimpleNamespace(id=CARD_ID, project_id=999))

    assert adapter.get_card_execution("p1", "c1") is None
