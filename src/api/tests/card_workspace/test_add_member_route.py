"""The additive route retains the native authentication and card-update policy."""

import json
from types import SimpleNamespace
from unittest.mock import Mock
import pytest
from fastapi import HTTPException
from langboard.routes.board.BoardCardApi import add_card_assignee
from langboard_shared.core.filter import AuthFilter
from langboard_shared.domain.models import ProjectRole
from langboard_shared.filter import RoleFilter


def test_add_member_has_authentication_and_card_update_guard():
    assert AuthFilter.exists(add_card_assignee)
    role, actions, _, admin_allowed = RoleFilter.get_filtered(add_card_assignee)
    assert role is ProjectRole
    assert actions == ["card_update"]
    assert admin_allowed


def test_add_member_returns_the_canonical_assignment_without_rewriting_other_members():
    result = {"changed": True, "member_uids": ["existing", "new"]}
    command = Mock(return_value=result)
    service = SimpleNamespace(card=SimpleNamespace(assign_member=command))
    actor = object()
    response = add_card_assignee("project", "card", "new", actor, service)
    assert json.loads(response.body) == result
    command.assert_called_once_with(actor, "project", "card", "new")


@pytest.mark.parametrize("error,code", [(LookupError(), "NF2003"), (ValueError(), "NF2005")])
def test_invalid_scope_or_member_uses_native_not_found(error, code):
    service = SimpleNamespace(card=SimpleNamespace(assign_member=Mock(side_effect=error)))
    with pytest.raises(HTTPException) as caught:
        add_card_assignee("project", "card", "member", object(), service)
    assert caught.value.status_code == 404
    assert caught.value.detail["code"] == code
