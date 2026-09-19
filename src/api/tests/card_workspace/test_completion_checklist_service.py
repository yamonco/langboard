import os
from types import SimpleNamespace
from typing import Any
import pytest
from sqlalchemy.exc import IntegrityError


os.environ.setdefault("PROJECT_NAME", "langboard")

from langboard_shared.core.db import EditorContentModel  # noqa: E402
from langboard_shared.domain.models import Card, Checklist, Project  # noqa: E402
from langboard_shared.domain.services.factory.CardService import CardService  # noqa: E402
from langboard_shared.domain.services.factory.ChecklistService import ChecklistService  # noqa: E402


def _card() -> Card:
    return Card(
        project_id=1,
        project_column_id=2,
        title="Ship it",
        description=EditorContentModel(),
    )


def _service(service_type: type[Any], repository: Any) -> Any:
    return service_type(lambda _type: None, lambda _name: None, repository)


@pytest.mark.parametrize("method_name", ["get_api_list_by_card", "get_api_list_only_by_card"])
def test_public_card_checklists_are_filtered_before_limit(method_name: str) -> None:
    calls: list[dict[str, Any]] = []

    def get_all_by_card(_card: Card, **kwargs: Any) -> list[Checklist]:
        calls.append(kwargs)
        return []

    repository = SimpleNamespace(checklist=SimpleNamespace(get_all_by_card=get_all_by_card))

    method = getattr(_service(ChecklistService, repository), method_name)
    if method_name == "get_api_list_by_card":
        method(_card(), limit=3)
        assert calls == [{"limit": 3, "is_system": False}]
    else:
        method(_card())
        assert calls == [{"is_system": False}]


def test_public_project_checklists_are_filtered_before_limit() -> None:
    calls: list[dict[str, Any]] = []

    def get_all_by_project(_project: Any, **kwargs: Any) -> list[Checklist]:
        calls.append(kwargs)
        return []

    repository = SimpleNamespace(checklist=SimpleNamespace(get_all_by_project=get_all_by_project))
    project = Project(owner_id=1, title="Board")

    _service(ChecklistService, repository).get_api_list_only_by_project(project, limit=4)

    assert calls == [{"limit": 4, "is_system": False}]


def test_concurrent_completion_creation_reuses_constraint_winner() -> None:
    winner = Checklist(card_id=1, title="", is_system=True)
    winner.id = 99
    lookups = 0

    def get_all_by_card(_card: Card, **kwargs: Any) -> list[Checklist]:
        nonlocal lookups
        lookups += 1
        return [] if lookups == 1 else [winner]

    def reject_duplicate(_checklist: Checklist, _checkitem: Any) -> None:
        raise IntegrityError("insert", {}, Exception("duplicate"))

    repository = SimpleNamespace(
        checklist=SimpleNamespace(
            get_all_by_card=get_all_by_card,
            get_next_order=lambda _card: 0,
            insert_completion=reject_duplicate,
        )
    )

    result = _service(CardService, repository).ensure_completion_checklist(_card())

    assert result is winner
    assert lookups == 2


def test_checklist_model_declares_one_active_system_row_constraint() -> None:
    index = next(index for index in Checklist.__table__.indexes if index.name == "uq_checklist_active_system_card")

    assert index.unique is True
    assert [column.name for column in index.columns] == ["card_id"]
    assert str(index.dialect_options["postgresql"]["where"]) == "is_system AND deleted_at IS NULL"
    assert str(index.dialect_options["sqlite"]["where"]) == "is_system = 1 AND deleted_at IS NULL"
