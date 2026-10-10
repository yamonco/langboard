"""The REST graph patch shares validation and calls the native transaction owner."""

import json
from types import SimpleNamespace
from unittest.mock import Mock
import pytest
from langboard.routes.board.BoardCardApi import patch_card_relationships
from langboard.routes.board.forms import PatchCardGraphForm
from langboard_shared.domain.models import User


def test_graph_patch_route_uses_native_owner_without_workspace_adapter(monkeypatch: pytest.MonkeyPatch) -> None:
    from langboard.routes.board import BoardCardApi

    monkeypatch.setattr(
        BoardCardApi,
        "NativeCardWorkspaceAdapter",
        lambda *args: pytest.fail("workspace adapter used"),
    )
    actor = User.model_construct(id=1)
    apply = Mock(return_value={"created_cards": [], "created_relationships": []})
    readable = Mock(return_value=(object(), object(), object()))
    service = SimpleNamespace(card_relationship=SimpleNamespace(apply_graph_patch=apply),
                              card=SimpleNamespace(resolve_readable_card=readable))
    request = SimpleNamespace(scope={})
    form = PatchCardGraphForm(
        new_cards=[{"client_ref": "new:a", "title": " A "}],
        add_edges=[{"parent_ref": "root", "child_ref": "new:a", "relationship_type_uid": "blocks"}],
    )

    response = patch_card_relationships("project", "root", request, form, actor, service)
    assert json.loads(response.body) == {"created_cards": [], "created_relationships": []}
    apply.assert_called_once_with(actor, "project", "root", [("new:a", "A", None)], [("root", "new:a", "blocks")], [])

    with pytest.raises(ValueError, match="at least one change"):
        patch_card_relationships("project", "root", request, PatchCardGraphForm(), actor, service)
    assert apply.call_count == 1


@pytest.mark.parametrize("operation", ["patch", "replace"])
@pytest.mark.parametrize("denial", ["cycle", "ownership"])
def test_known_domain_denial_maps_to_native_http_status(operation, denial):
    from langboard.routes.board.BoardCardApi import update_card_relationships
    from langboard.routes.board.forms import UpdateCardRelationshipsForm
    from langboard_shared.core.exceptions.RelationshipCycle import RelationshipCycle
    from langboard_shared.core.routing import ApiException
    from langboard_shared.domain.services.AppGovernance import AppGovernanceDenied

    error = RelationshipCycle("Relationship would create a blocks cycle") if denial == "cycle" else AppGovernanceDenied()
    reject = Mock(side_effect=error)
    service = SimpleNamespace(card_relationship=SimpleNamespace(apply_graph_patch=reject, update=reject),
                              card=SimpleNamespace(resolve_readable_card=Mock(return_value=(object(), object(), object()))))
    request = SimpleNamespace(scope={})
    actor = User.model_construct(id=1)
    exception = ApiException.BadRequest_400 if denial == "cycle" else ApiException.Forbidden_403
    with pytest.raises(exception) as failure:
        if operation == "patch":
            form = PatchCardGraphForm(
                add_edges=[{"parent_ref": "root", "child_ref": "child", "relationship_type_uid": "blocks"}]
            )
            patch_card_relationships("project", "root", request, form, actor, service)
        else:
            form = UpdateCardRelationshipsForm(is_parent=False, relationships=[("child", "blocks")])
            update_card_relationships("project", "root", request, form, actor, service)
    assert failure.value.status_code == (400 if denial == "cycle" else 403)
    assert reject.call_count == 1
