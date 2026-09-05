"""Wiki and self-assignment public MCP contract proof, colocated with the new workflow."""

import os
from types import SimpleNamespace
from unittest.mock import Mock, patch
import pytest


os.environ.setdefault("PROJECT_NAME", "langboard")

from fastmcp.exceptions import AuthorizationError, ValidationError
from langboard_shared.domain.services.factory.CardService import CardService
from langboard.mcp_integration import McpTool
from langboard.mcp_tools import CardWorkspaceMcp, WikiWorkspaceMcp
from langboard.wiki_workspace.domain import WikiSnapshot
from langboard.wiki_workspace.infrastructure import NativeWikiRepository


def test_self_assignment_identity_is_never_a_caller_argument() -> None:
    """The authenticated user, not model-guessed email or UID, controls self-assignment."""
    schema = McpTool.get_tool("assign_card_to_me")["input_schema"]
    assert set(schema["properties"]) == {"project_uid", "card_uid"}
    user = object()
    service = SimpleNamespace(card=SimpleNamespace(assign_self=Mock(return_value={"changed": True})))
    CardWorkspaceMcp.assign_card_to_me("p", "c", user, service)
    service.card.assign_self.assert_called_once_with(user, "p", "c")


def test_additive_self_assignment_is_noop_when_already_assigned() -> None:
    """Do not replace the entire member set or emit duplicate events on replay."""
    user = SimpleNamespace(id=1, get_uid=lambda: "me")
    card = SimpleNamespace(get_uid=lambda: "c")
    repo = SimpleNamespace(
        project_assigned_user=SimpleNamespace(find_by_user_and_project=Mock(return_value=object())),
        card_assigned_user=SimpleNamespace(
            get_all_by_card=Mock(return_value=[(1, object()), (2, object())]), add_member=Mock(return_value=False)
        ),
    )
    service = CardService(lambda _: None, lambda _: None, repo)
    with patch(
        "langboard_shared.domain.services.factory.CardService.InfraHelper.get_records_with_foreign_by_params",
        return_value=(object(), card),
    ):
        assert service.assign_self(user, "p", "c") == {"card_uid": "c", "assigned_user_uid": "me", "changed": False}
    repo.card_assigned_user.add_member.assert_called_once()


def test_private_wiki_denies_content_and_history_before_loading_activity() -> None:
    """A project member without private-wiki access gets neither current nor old body."""
    wiki = SimpleNamespace(project_id=1)
    service = SimpleNamespace(
        project=SimpleNamespace(get_by_id_like=lambda _: SimpleNamespace(id=1)),
        project_wiki=SimpleNamespace(
            get_by_id_like=lambda _: wiki, convert_to_api_response=lambda *_: {"forbidden": True}
        ),
    )
    repository = NativeWikiRepository(SimpleNamespace(), service)
    with pytest.raises(AuthorizationError):
        repository.snapshot("p", "w")
    with pytest.raises(AuthorizationError):
        repository.revisions("p", "w", None, 20)
    with pytest.raises(AuthorizationError):
        repository.revision_page("p", "w", "r", "after", None, 100)


def test_stale_append_is_rejected_before_storage() -> None:
    """Stale revision reports validation, but unrelated post-save failures are not mislabeled."""
    repository = Mock()
    repository.snapshot.return_value = WikiSnapshot("w", "title", "original")
    with patch.object(WikiWorkspaceMcp, "NativeWikiRepository", return_value=repository):
        with pytest.raises(ValidationError):
            WikiWorkspaceMcp.append_wiki_content("p", "w", "stale", "add", None, None)
        repository.append.assert_not_called()
        repository.append.side_effect = RuntimeError("post-save publisher failure")
        with pytest.raises(RuntimeError):
            WikiWorkspaceMcp.append_wiki_content("p", "w", repository.snapshot.return_value.revision, "add", None, None)
