import os
from types import SimpleNamespace
import orjson
import pytest


os.environ.setdefault("PROJECT_NAME", "langboard")

from langboard.mcp_tools.UserMcp import list_my_work  # noqa: E402
from langboard.routes.dashboard.DashboardApi import get_assigned_work, get_my_work  # noqa: E402
from langboard_shared.core.routing import ApiException  # noqa: E402


def test_my_work_limits_query_to_authorized_project() -> None:
    calls = []
    user = SimpleNamespace()
    service = SimpleNamespace(
        project=SimpleNamespace(get_api_list=lambda _user: ([{"uid": "allowed"}, {"uid": "other"}], [])),
        notification=SimpleNamespace(get_mentioned_card_ids=lambda _user: [7]),
        card=SimpleNamespace(get_my_work_cards=lambda *args: calls.append(args) or [{"uid": "card-1"}]),
    )

    response = get_my_work(project_uid="allowed", limit=20, user=user, service=service)

    assert orjson.loads(response.body) == {"cards": [{"uid": "card-1"}]}
    assert calls[0][0] is user
    assert calls[0][1] == [{"uid": "allowed"}]
    assert calls[0][3] == [7]
    assert calls[0][-1] == 20


def test_my_work_rejects_project_outside_current_access() -> None:
    user = SimpleNamespace()
    service = SimpleNamespace(
        project=SimpleNamespace(get_api_list=lambda _user: ([{"uid": "allowed"}], [])),
        notification=SimpleNamespace(get_mentioned_card_ids=lambda _user: pytest.fail("notification lookup must not run")),
        card=SimpleNamespace(get_my_work_cards=lambda *_args: pytest.fail("card query must not run")),
    )

    with pytest.raises(ApiException.NotFound_404):
        get_my_work(project_uid="revoked", limit=20, user=user, service=service)


def test_rest_and_mcp_assigned_work_share_query_and_cursor_contract() -> None:
    calls = []
    result = {"items": [{"card_uid": "card-1"}], "next_cursor": "next"}
    service = SimpleNamespace(card=SimpleNamespace(list_assigned_work=lambda *args: calls.append(args) or result))
    user = object()
    response = get_assigned_work(project_uid="board", cursor="prior", limit=7, user=user, service=service)
    assert orjson.loads(response.body) == list_my_work(user, service, "board", "prior", 7) == result
    assert calls == [(user, "board", "prior", 7)] * 2


def test_assigned_work_invalid_query_is_a_client_error() -> None:
    def invalid(*_):
        raise ValueError("Invalid My Work cursor")
    service = SimpleNamespace(card=SimpleNamespace(list_assigned_work=invalid))
    with pytest.raises(ApiException.BadRequest_400):
        get_assigned_work(cursor="bad", limit=20, user=object(), service=service)
