import os
from datetime import timezone
from types import SimpleNamespace
import pytest


os.environ.setdefault("PROJECT_NAME", "langboard")

from langboard.mcp_integration import McpTool  # noqa: E402
from langboard.mcp_tools import UserWorkspaceMcp  # noqa: E402
from langboard_shared.domain.services.factory.NotificationService import NotificationService  # noqa: E402
from langboard_shared.helpers import InfraHelper  # noqa: E402


def test_unread_query_is_bounded_side_effect_free_and_project_governed() -> None:
    """Unread lookup requests only unread rows and hides stale project access."""

    calls: list[tuple] = []
    user = SimpleNamespace()

    def get_api_list(*args: object, **kwargs: object) -> tuple[list[dict], bool, int]:
        calls.append((args, kwargs))
        return (
            [
                {"uid": "n1", "type": "mentioned_in_card", "records": {"project": {"uid": "allowed"}}},
                {"uid": "n3", "type": "project_invited", "records": {"project": {"uid": "invited"}}},
            ],
            False,
            3,
        )

    service = SimpleNamespace(
        notification=SimpleNamespace(get_api_list=get_api_list),
    )

    result = UserWorkspaceMcp.get_unread_notifications(user, service, limit=10)

    assert [notification["uid"] for notification in result["notifications"]] == ["n1", "n3"]
    assert result["returned_count"] == 2
    assert "has_more" not in result
    assert "unread_count" not in result
    assert calls == [((user, "all", 1, 10), {"unread_only": True, "authorized_projects_only": True})]


def test_notification_read_tools_mutate_only_when_called() -> None:
    """Read mutations remain separate from the unread query."""

    user = SimpleNamespace()
    read_calls: list[tuple] = []
    read_all_calls: list[object] = []
    service = SimpleNamespace(
        notification=SimpleNamespace(
            read=lambda *args: not read_calls.append(args),
            read_all=lambda actor: read_all_calls.append(actor),
        )
    )

    assert UserWorkspaceMcp.mark_notification_read("notification-1", user, service) == {"read": True}
    assert UserWorkspaceMcp.mark_all_notifications_read(user, service) == {"read": True}
    assert read_calls == [(user, "notification-1")]
    assert read_all_calls == [user]


def test_unread_service_query_does_not_cleanup_missing_references(monkeypatch: pytest.MonkeyPatch) -> None:
    """Unread MCP reads stay side-effect free even when an old reference is gone."""

    notification = SimpleNamespace(
        id=1,
        notifier_type="user",
        notifier_id=2,
        record_list=[("project", 3)],
    )
    deleted: list[list[int]] = []
    user_notification = SimpleNamespace(
        get_list=lambda *args: [notification],
        count_unread=lambda _user: 1,
        delete_all_by_ids=lambda ids: deleted.append(ids),
    )
    service = NotificationService(
        lambda *_: None, lambda *_: None, SimpleNamespace(user_notification=user_notification)
    )
    monkeypatch.setattr(InfraHelper, "get_references", lambda *_args, **_kwargs: {})

    assert service.get_api_list(SimpleNamespace(), "all", unread_only=True) == ([], False, 1)
    assert deleted == []


def test_project_search_reuses_native_bounded_search() -> None:
    """Search delegates to the existing project-scoped implementation."""

    calls: list[tuple[str, str]] = []
    service = SimpleNamespace(
        card=SimpleNamespace(
            search_context_by_project=lambda project_uid, query, **_filters: calls.append((project_uid, query))
            or [{"uid": "c1"}]
        )
    )

    assert UserWorkspaceMcp.search_project_cards("project-1", "  release  ", service) == {"cards": [{"uid": "c1"}]}
    assert calls == [("project-1", "release")]


def test_project_search_normalizes_offset_bounds_to_utc() -> None:
    """Offset-aware bounds compare consistently with UTC-backed database timestamps."""

    captured: dict[str, object] = {}
    service = SimpleNamespace(
        card=SimpleNamespace(search_context_by_project=lambda *_args, **filters: captured.update(filters) or [])
    )

    UserWorkspaceMcp.search_project_cards(
        "project-1",
        "release",
        service,
        since="2026-09-20T09:00:00+09:00",
        until="2026-09-20T10:00:00+09:00",
    )

    assert captured["since"].tzinfo == timezone.utc
    assert captured["since"].isoformat() == "2026-09-20T00:00:00+00:00"
    assert captured["until"].isoformat() == "2026-09-20T01:00:00+00:00"


def test_my_work_lookup_is_governed_read_only_and_notified_read_state_independent() -> None:
    """My Work reads only accessible projects and never invokes notification reads."""

    calls: list[list[str]] = []
    user = SimpleNamespace()

    def get_my_work_cards(_user, project_uids, _purposes, _mentioned, _due, _field, _since, _until, _limit):
        calls.append(project_uids)
        return [{"uid": "c1"}]

    service = SimpleNamespace(
        project=SimpleNamespace(get_api_list=lambda _user: ([{"uid": "allowed"}, {"uid": "revoked"}], [])),
        notification=SimpleNamespace(get_mentioned_card_ids=lambda _user: [101]),
        card=SimpleNamespace(get_my_work_cards=get_my_work_cards),
    )

    result = UserWorkspaceMcp.get_my_work_cards(
        user,
        service,
        purposes=["mentioned"],
        project_uid="allowed",
        limit=10,
    )

    assert result == {"cards": [{"uid": "c1"}], "returned_count": 1}
    assert calls == [[{"uid": "allowed"}]]


def test_my_work_due_filters_include_mentioned_cards_and_normalize_bounds() -> None:
    """Temporal purposes preserve mention-only ownership and UTC date comparisons."""

    captured: list[object] = []
    user = SimpleNamespace()

    def get_my_work_cards(*args):
        captured.extend(args)
        return []

    mention_calls: list[object] = []
    service = SimpleNamespace(
        project=SimpleNamespace(get_api_list=lambda _user: ([{"uid": "allowed"}], [])),
        notification=SimpleNamespace(get_mentioned_card_ids=lambda actor: mention_calls.append(actor) or [101]),
        card=SimpleNamespace(get_my_work_cards=get_my_work_cards),
    )

    UserWorkspaceMcp.get_my_work_cards(
        user,
        service,
        purposes=["due_soon"],
        since="2026-09-20T09:00:00+09:00",
        until="2026-09-20T10:00:00+09:00",
    )

    assert mention_calls == [user]
    assert captured[3] == [101]
    assert captured[6].isoformat() == "2026-09-20T00:00:00+00:00"
    assert captured[7].isoformat() == "2026-09-20T01:00:00+00:00"


def test_user_workspace_tool_schemas_keep_reads_and_mutations_distinct() -> None:
    """Tool schemas expose explicit unread and read-transition commands."""

    assert McpTool.get_tool("get_unread_notifications")["input_schema"].get("required", []) == []
    assert McpTool.get_tool("mark_notification_read")["input_schema"]["required"] == ["notification_uid"]
    assert McpTool.get_tool("mark_all_notifications_read")["input_schema"].get("required", []) == []
    assert McpTool.get_tool("search_project_cards")["input_schema"]["required"] == ["project_uid", "query"]
    assert McpTool.get_tool("get_my_work_cards")["input_schema"].get("required", []) == []
    my_work_properties = McpTool.get_tool("get_my_work_cards")["input_schema"]["properties"]
    assert (
        my_work_properties["due_within_days"] | {"minimum": 1, "maximum": 30} == my_work_properties["due_within_days"]
    )
    assert my_work_properties["limit"] | {"minimum": 1, "maximum": 50} == my_work_properties["limit"]


@pytest.mark.parametrize("query", ["", " ", "x" * 1001])
def test_project_search_rejects_empty_or_oversized_queries(query: str) -> None:
    """Search rejects unbounded or empty model input before repository access."""

    with pytest.raises(ValueError):
        UserWorkspaceMcp.search_project_cards("project-1", query, SimpleNamespace())
