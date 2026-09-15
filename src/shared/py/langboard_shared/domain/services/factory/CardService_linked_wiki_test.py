from importlib import import_module
from types import SimpleNamespace
from unittest.mock import Mock
import pytest
from .CardService import CardService


@pytest.mark.parametrize("actor", [None, SimpleNamespace(is_admin=True), SimpleNamespace(is_admin=False), object()])
def test_private_wiki_cannot_create_or_return_a_board_link(monkeypatch: pytest.MonkeyPatch, actor: object) -> None:
    module = import_module(CardService.__module__)
    project = SimpleNamespace(id=1)
    wiki = SimpleNamespace(project_id=1, is_public=False)
    monkeypatch.setattr(module.InfraHelper, "get_records_with_foreign_by_params", lambda *args: (project, wiki))
    repo = Mock()
    service = SimpleNamespace(repo=repo)

    assert CardService.create_linked_wiki_card(service, actor, project, wiki) is None
    assert not repo.mock_calls
