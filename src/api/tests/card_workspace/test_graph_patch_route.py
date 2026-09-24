"""The REST graph patch shares validation and calls the native transaction owner."""

import json
from types import SimpleNamespace
from unittest.mock import Mock
import pytest
from langboard.routes.board.BoardCardApi import patch_card_relationships
from langboard.routes.board.forms import PatchCardGraphForm


def test_graph_patch_route_uses_native_owner_without_workspace_adapter(monkeypatch: pytest.MonkeyPatch) -> None:
    from langboard.routes.board import BoardCardApi

    monkeypatch.setattr(
        BoardCardApi,
        "NativeCardWorkspaceAdapter",
        lambda *args: pytest.fail("workspace adapter used"),
    )
    actor = object()
    apply = Mock(return_value={"created_cards": [], "created_relationships": []})
    service = SimpleNamespace(card_relationship=SimpleNamespace(apply_graph_patch=apply))
    form = PatchCardGraphForm(
        new_cards=[{"client_ref": "new:a", "title": " A "}],
        add_edges=[{"parent_ref": "root", "child_ref": "new:a", "relationship_type_uid": "blocks"}],
    )

    response = patch_card_relationships("project", "root", form, actor, service)
    assert json.loads(response.body) == {"created_cards": [], "created_relationships": []}
    apply.assert_called_once_with(actor, "project", "root", [("new:a", "A", None)], [("root", "new:a", "blocks")], [])

    with pytest.raises(ValueError, match="at least one change"):
        patch_card_relationships("project", "root", PatchCardGraphForm(), actor, service)
    assert apply.call_count == 1
