import importlib
import os
from types import SimpleNamespace
from typing import Any
import pytest


os.environ.setdefault("PROJECT_NAME", "langboard")

from langboard.card_workspace.application.dtos import CardBundleDto, CardBundleResponse  # noqa: E402
from langboard.mcp_integration import McpTool  # noqa: E402
from langboard.mcp_tools import BotMcp, CardMcp, CardWorkspaceMcp, MetadataMcp, ProjectMcp  # noqa: E402, F401
from langboard.routes.mcp.McpApi import serialize_mcp_result  # noqa: E402
from langboard_shared.domain.models.bases import REACTION_TYPES  # noqa: E402
from langboard_shared.domain.services.factory.CardService import CardService  # noqa: E402


def test_card_partial_edit_schema_requires_only_card_identity() -> None:
    """Partial detail fields remain optional while an explicit identity is always required."""

    schema = McpTool.get_tool("change_card_details")["input_schema"]

    assert schema["required"] == ["project_uid", "card_uid"]
    assert schema["properties"]["title"]["default"] is None
    assert schema["properties"]["description"]["default"] is None
    assert schema["properties"]["deadline_at"]["default"] is None


def test_card_move_schema_makes_column_an_optional_destination() -> None:
    """Reordering in place requires no synthetic nullable column argument."""

    schema = McpTool.get_tool("change_card_order_or_move_column")["input_schema"]

    assert schema["required"] == ["project_uid", "card_uid", "order"]
    assert schema["properties"]["column_uid"]["default"] is None


def test_card_bundle_schema_exposes_opt_in_sections() -> None:
    """Agents can request rich sections without paying for them by default."""

    schema = McpTool.get_tool("get_card_bundle")["input_schema"]

    assert schema["$defs"]["CardBundleInclude"]["enum"] == [
        "description",
        "people",
        "classification",
        "checklists",
        "comments",
        "attachments",
        "metadata",
        "automation",
    ]
    assert schema["properties"]["include"]["default"] is None


def test_comment_reaction_schema_exposes_only_native_reactions() -> None:
    """Agents cannot invent reaction values unsupported by Langboard clients."""

    schema = McpTool.get_tool("toggle_card_comment_reaction")["input_schema"]

    assert schema["properties"]["reaction"]["enum"] == REACTION_TYPES


def test_mcp_serializer_omits_unrequested_card_sections() -> None:
    """The real MCP response path does not leak optional sections as null placeholders."""

    result = serialize_mcp_result(
        CardBundleResponse(
            card_uid="card-1",
            card=CardBundleDto(core={"uid": "card-1", "title": "Work"}, workflow={}),
        )
    )

    assert result == {
        "card_uid": "card-1",
        "card": {"core": {"uid": "card-1", "title": "Work"}, "workflow": {}},
        "continuation": None,
    }


def test_project_member_projection_omits_email_and_is_bounded() -> None:
    """Room tools receive assignable identities without the private directory."""

    service = SimpleNamespace(
        project=SimpleNamespace(
            get_by_id_like=lambda _uid: object(),
            get_api_assigned_user_list=lambda _project, limit: [
                {"uid": str(index), "username": f"member-{index}", "email": "hidden@example.com"}
                for index in range(limit)
            ],
            count_assigned_users=lambda _project: 51,
        )
    )

    result = CardWorkspaceMcp.list_project_members("project", service)

    assert len(result["items"]) == 50
    assert result["truncated"] is True
    assert "email" not in str(result)


@pytest.mark.parametrize(
    "tool_name",
    [
        "get_projects",
        "get_starred_projects",
        "get_project_assigned_users",
        "get_project_columns",
        "get_project_labels",
        "get_project_checklists",
        "get_column_bot_scopes",
        "get_column_bot_schedules",
        "get_cards",
        "get_card",
        "get_card_checklists",
        "get_card_attachments",
        "get_card_metadata",
        "get_wiki_metadata",
        "get_project_bot_scopes",
        "get_card_bot_scopes",
    ],
)
def test_legacy_mcp_list_tools_have_bounded_limits(tool_name: str) -> None:
    limit_schema = McpTool.get_tool(tool_name)["input_schema"]["properties"]["limit"]

    assert limit_schema == {"default": 50, "minimum": 1, "maximum": 100, "type": "integer"}


def test_project_detail_has_a_bounded_limit() -> None:
    limit_schema = McpTool.get_tool("get_project")["input_schema"]["properties"]["limit"]

    assert limit_schema == {"default": 50, "minimum": 1, "maximum": 100, "type": "integer"}


def test_bot_scope_tool_names_resolve_to_project_checked_implementations() -> None:
    assert McpTool.get_tool("get_card_bot_scopes")["handler"] is BotMcp.get_card_bot_scopes
    assert McpTool.get_tool("get_column_bot_scopes")["handler"] is BotMcp.get_column_bot_scopes


def test_column_bot_scopes_query_the_requested_column_before_limiting() -> None:
    column = SimpleNamespace(project_id=1)
    calls: list[tuple[object, int]] = []
    service = SimpleNamespace(
        project_column=SimpleNamespace(
            get_by_id_like=lambda _uid: column,
            get_api_bot_scopes_by_column=lambda target, limit: (
                calls.append((target, limit)),
                [{"uid": "scope-one"}],
            )[1],
        ),
        bot=SimpleNamespace(require_target_project=lambda *_args: None),
    )

    result = BotMcp.get_column_bot_scopes("project-one", "column-one", service, limit=5)

    assert result == {"scopes": [{"uid": "scope-one"}]}
    assert calls == [(column, 5)]


def test_project_column_schedules_apply_the_limit_to_schedules() -> None:
    project = object()
    calls: list[tuple[object, int]] = []
    service = SimpleNamespace(
        project=SimpleNamespace(get_by_id_like=lambda _uid: project),
        project_column=SimpleNamespace(
            get_api_bot_schedule_list_by_project=lambda target, limit: (
                calls.append((target, limit)),
                [{"uid": "schedule-one"}],
            )[1]
        ),
    )

    result = ProjectMcp.get_column_bot_schedules("project-one", service, limit=5)

    assert result == {"column_bot_schedules": [{"uid": "schedule-one"}]}
    assert calls == [(project, 5)]


def test_duplicate_mcp_tool_names_fail_at_registration() -> None:
    with pytest.raises(ValueError, match="Duplicate MCP tool name"):

        @McpTool.add(description="Duplicate")
        def get_cards() -> None:
            return None


def test_empty_partial_edit_and_invalid_order_stop_before_service() -> None:
    """No-op and malformed multi-field writes never reach the native service."""

    calls: list[tuple[Any, ...]] = []
    service = SimpleNamespace(
        card=SimpleNamespace(
            update=lambda *args: calls.append(args),
            change_order=lambda *args: calls.append(args),
        )
    )

    with pytest.raises(ValueError, match="At least one"):
        CardMcp.change_card_details("p", "c", object(), service)
    with pytest.raises(ValueError, match="non-negative"):
        CardMcp.change_card_order_or_move_column("p", "c", -1, object(), service)

    assert calls == []


def test_native_archive_rejects_card_outside_project(monkeypatch: pytest.MonkeyPatch) -> None:
    """Native archive validates the project-card ancestry before any write."""

    module = importlib.import_module("langboard_shared.domain.services.factory.CardService")
    monkeypatch.setattr(
        module.InfraHelper,
        "get_records_with_foreign_by_params",
        lambda *args: None,
    )

    assert CardService.archive(object(), object(), "project-a", "card-from-b") is None


def test_native_move_rejects_column_from_another_project(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Native move validates destination column ancestry before touching row order."""

    module = importlib.import_module("langboard_shared.domain.services.factory.CardService")
    project = SimpleNamespace(id=1)
    card = SimpleNamespace(project_id=1, project_column_id=10)
    old_column = SimpleNamespace(id=10, project_id=1)
    foreign_column = SimpleNamespace(id=20, project_id=2)
    monkeypatch.setattr(
        module.InfraHelper,
        "get_records_with_foreign_by_params",
        lambda *args: (project, card),
    )
    monkeypatch.setattr(
        module.InfraHelper,
        "get_by_id_like",
        lambda model, value: old_column if value == 10 else foreign_column,
    )

    assert CardService.change_order(SimpleNamespace(), object(), project, card, 0, foreign_column) is None
