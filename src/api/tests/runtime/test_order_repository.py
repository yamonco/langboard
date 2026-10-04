from collections.abc import Iterator
from contextlib import contextmanager
from unittest.mock import MagicMock
import pytest
from langboard_shared.core.db import DbSession
from langboard_shared.infrastructure.repositories.factory.CardRepository import CardRepository
from langboard_shared.infrastructure.repositories.factory.CheckitemRepository import CheckitemRepository


@pytest.mark.parametrize(
    ("repository", "parent_field"),
    [(CardRepository, "project_column_id"), (CheckitemRepository, "checklist_id")],
)
def test_move_persists_destination_parent_and_order(
    monkeypatch: pytest.MonkeyPatch,
    repository: type[CardRepository] | type[CheckitemRepository],
    parent_field: str,
) -> None:
    db = MagicMock()

    @contextmanager
    def use(readonly: bool) -> Iterator[MagicMock]:
        assert not readonly
        yield db

    monkeypatch.setattr(DbSession, "use", use)

    repository(lambda _: None, lambda _: None).update_row_order(11, 21, 1, 0, 22)

    assert db.exec.call_count == 3
    old_parent_update = db.exec.call_args_list[0].args[0]
    assert '"order" >' in str(old_parent_update)
    final_update = db.exec.call_args_list[-1].args[0]
    values = final_update.compile().params
    assert values["order"] == 0
    assert values[parent_field] == 22


@pytest.mark.parametrize("repository", [CardRepository, CheckitemRepository])
def test_same_parent_reorder_does_not_move_parent(
    monkeypatch: pytest.MonkeyPatch, repository: type[CardRepository] | type[CheckitemRepository]
) -> None:
    db = MagicMock()

    @contextmanager
    def use(readonly: bool) -> Iterator[MagicMock]:
        assert not readonly
        yield db

    monkeypatch.setattr(DbSession, "use", use)

    repository(lambda _: None, lambda _: None).update_row_order(11, 21, 1, 0, 21)

    assert db.exec.call_count == 2
    values = db.exec.call_args_list[-1].args[0].compile().params
    assert values["order"] == 0
    assert "checklist_id" not in values
    assert "project_column_id" not in values


def test_card_checkitems_are_read_in_order(monkeypatch: pytest.MonkeyPatch) -> None:
    db = MagicMock()

    @contextmanager
    def use(readonly: bool) -> Iterator[MagicMock]:
        assert readonly
        yield db

    monkeypatch.setattr(DbSession, "use", use)

    CheckitemRepository(lambda _: None, lambda _: None).get_all_by_card(11)

    query = db.exec.call_args.args[0]
    order_by = [str(column) for column in query._order_by_clauses]
    assert order_by == ['checkitem."order" ASC', "checkitem.id ASC"]
