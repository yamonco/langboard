import importlib
import os
from types import SimpleNamespace
from typing import Any
import pytest


os.environ.setdefault("PROJECT_NAME", "langboard")

from langboard.card_workspace.application.dtos import CardBundleDto, CardBundleResponse  # noqa: E402
from langboard.mcp_integration import McpTool  # noqa: E402
from langboard.mcp_tools import CardMcp, CardWorkspaceMcp  # noqa: E402, F401
from langboard.routes.mcp.McpApi import serialize_mcp_result  # noqa: E402
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


def test_graph_patch_schema_exposes_typed_request_local_references() -> None:
    """Clients can mix existing UIDs and request-local cards in one explicit patch."""

    schema = McpTool.get_tool("apply_card_graph_patch")["input_schema"]

    assert schema["required"] == [
        "project_uid",
        "anchor_card_uid",
        "new_cards",
        "add_edges",
        "remove_relationship_uids",
    ]
    assert schema["$defs"]["CardGraphNewCard"]["required"] == ["client_ref", "title"]
    assert schema["$defs"]["CardGraphEdge"]["required"] == [
        "parent_ref",
        "child_ref",
        "relationship_type_uid",
    ]


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
            get_api_assigned_user_list=lambda _project: [
                {"uid": str(index), "username": f"member-{index}", "email": "hidden@example.com"} for index in range(51)
            ],
        )
    )

    result = CardWorkspaceMcp.list_project_members("project", service)

    assert len(result["items"]) == 50
    assert result["truncated"] is True
    assert "email" not in str(result)


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
