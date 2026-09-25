"""My Work result projection tests."""

from types import SimpleNamespace
from unittest.mock import Mock
from ....core.types import SafeDateTime
from .CardService import CardService


def test_assigned_only_card_reports_assigned_reason() -> None:
    """A card selected only through assignment never returns an empty reason list."""

    now = SafeDateTime.now()
    card = SimpleNamespace(
        id=10,
        title="Assigned",
        deadline_at=None,
        created_by_user_id=2,
        updated_at=now,
        get_uid=lambda: "card-1",
    )
    project = SimpleNamespace(title="Project", get_uid=lambda: "project-1")
    column = SimpleNamespace(name="Doing")
    repo = SimpleNamespace(card=SimpleNamespace(get_my_work_page=Mock(return_value=[(card, project, column, True)])))
    service = CardService(lambda _: None, lambda _: None, repo)

    result = service.get_my_work_cards(
        SimpleNamespace(id=1),
        [{"uid": "project-1"}],
        {"assigned"},
        [],
        now,
        "updated_at",
        None,
        None,
        20,
    )

    assert result[0]["reasons"] == ["assigned"]
