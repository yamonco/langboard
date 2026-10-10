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


@pytest.mark.parametrize("operation", ["patch", "replace"])
def test_known_block_cycle_returns_bad_request_for_both_rest_paths(operation):
    from langboard.routes.board.BoardCardApi import update_card_relationships
    from langboard.routes.board.forms import UpdateCardRelationshipsForm
    from langboard_shared.core.exceptions.RelationshipCycle import RelationshipCycle
    from langboard_shared.core.routing import ApiException

    reject = Mock(side_effect=RelationshipCycle("Relationship would create a blocks cycle"))
    service = SimpleNamespace(card_relationship=SimpleNamespace(apply_graph_patch=reject, update=reject))
    with pytest.raises(ApiException.BadRequest_400) as failure:
        if operation == "patch":
            form = PatchCardGraphForm(
                add_edges=[{"parent_ref": "root", "child_ref": "child", "relationship_type_uid": "blocks"}]
            )
            patch_card_relationships("project", "root", form, object(), service)
        else:
            form = UpdateCardRelationshipsForm(is_parent=False, relationships=[("child", "blocks")])
            update_card_relationships("project", "root", form, object(), service)
    assert failure.value.status_code == 400
    assert reject.call_count == 1
