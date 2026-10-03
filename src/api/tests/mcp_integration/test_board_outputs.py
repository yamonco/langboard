"""Native board guidance and omitted partial edits survive modern transport."""

import json
from types import SimpleNamespace
import pytest
from fastmcp import Client
from langboard.mcp_integration.BoardOutputs import BOARD_OUTPUTS
from langboard.mcp_integration.Server import McpServer
from langboard.mcp_integration.Tool import McpTool
from langboard.mcp_tools import CardMcp, ProjectMcp
from langboard.middlewares.McpAuthMiddleware import mcp_auth_context
from langboard_shared.domain.models import ProjectColumn, WorkflowStageDefinition
from langboard_shared.domain.services.factory.ProjectColumnService import ProjectColumnService
from pydantic import TypeAdapter


def native_column():
    return ProjectColumn(
        id=123,
        project_id=456,
        name="Review",
        description="칼럼 설명",
        workflow_stage="review",
        translations={"ko": {"name": "검토"}, "ja": {"description": "説明"}},
    )


def native_column_service(column):
    stage = WorkflowStageDefinition(key="review", name="Review", description="단계 설명", counts_as_completed=False)
    repo = SimpleNamespace(
        project_column=SimpleNamespace(
            get_all_by_project=lambda _: [(column, 4)],
            get_work_counts=lambda _: {column.id: {"open_count": 2, "incomplete_count": 3}},
        ),
        workflow_stage=SimpleNamespace(get_by_keys=lambda _: {"review": stage}),
    )
    return ProjectColumnService(lambda _: None, lambda _: None, repo)


def test_native_column_projection_keeps_combined_guidance_and_locale_omissions():
    column = native_column()
    expected = native_column_service(column).get_api_list_by_project("project")[0]
    actual = BOARD_OUTPUTS["create_column"].model_validate(expected).model_dump(mode="json")
    assert actual == TypeAdapter(dict).dump_python(expected, mode="json")
    assert actual["workflow_guidance"] == "Workflow stage:\n단계 설명\n\nColumn:\n칼럼 설명"
    assert actual["translations"]["ko"] == {"name": "검토"}
    assert actual["open_count"] == 2 and actual["count"] == 4


def test_actual_template_board_handler_preserves_missing_guidance(monkeypatch):
    column = native_column()
    native = SimpleNamespace(
        create_project=lambda *args: (
            SimpleNamespace(get_uid=lambda: "board", title="Board", project_type="Other"),
            [column],
            SimpleNamespace(name="Template"),
        )
    )
    service = SimpleNamespace(project_template=native)
    monkeypatch.setattr(ProjectMcp, "User", SimpleNamespace)
    expected = ProjectMcp.create_project_board("Board", SimpleNamespace(), service)
    actual = BOARD_OUTPUTS["create_project_board"].model_validate(expected).model_dump(mode="json")
    assert actual == TypeAdapter(dict).dump_python(expected, mode="json")
    assert "workflow_guidance" not in actual["columns"][0]
    assert "open_count" not in actual["columns"][0]


@pytest.mark.parametrize(
    "payload",
    [
        {"title": "New"},
        {"deadline_at": None},
        {"deadline_at": ""},
        {"title": "New", "deadline_at": "2026-10-04T09:00:00Z"},
    ],
)
def test_actual_card_details_handler_retains_partial_result(monkeypatch, payload):
    monkeypatch.setattr(CardMcp, "_require_task_card", lambda *args: None)
    service = SimpleNamespace(card=SimpleNamespace(update=lambda *args: payload))
    expected = CardMcp.change_card_details("board", "card", object(), service, title="New")
    assert BOARD_OUTPUTS["change_card_details"].model_validate(expected).model_dump(mode="json") == payload


@pytest.mark.parametrize("profile", ["raw", "compatibility"])
@pytest.mark.parametrize("malformed", [False, True])
async def test_column_reorder_native_handler_and_postsave_receipt(monkeypatch, profile, malformed):
    column = native_column()
    archive = ProjectColumn(id=124, project_id=456, name="Archive", is_archive=True, order=1)
    native = native_column_service(column)
    effects = []

    def columns(_):
        result = native.get_api_list_by_project("board")
        if malformed and effects:
            result[0]["translations"]["ko"]["name"] = 1
        return result + [{**archive.api_response(), "count": 0}]

    service = SimpleNamespace(
        project=SimpleNamespace(get_by_id_like=lambda _: object()),
        project_column=SimpleNamespace(
            get_api_list_by_project=columns, change_order=lambda *args: effects.append(args) or True
        ),
    )
    expected = {"column_uid": column.get_uid(), "columns": native.get_api_list_by_project("board")}

    def handler(order: int) -> dict:
        return ProjectMcp.change_column_order("board", column.get_uid(), order, service)

    name = "change_column_order"
    metadata = {"handler": handler, "description": "Reorder", "exclude": [], "accessible_type": "all"}
    monkeypatch.setattr(McpTool, "get_tools", lambda: {name: metadata})
    monkeypatch.setattr(McpTool, "get_tool", lambda key: metadata if key == name else None)
    monkeypatch.setattr(McpServer, "_validate_auth", lambda *args: True)
    monkeypatch.setattr(McpServer, "_validate_role", lambda *args, **kwargs: True)
    _, server = McpServer.get_http_app(profile)
    token = mcp_auth_context.set(
        {"user_or_bot": object(), "tool_group": SimpleNamespace(activated_at=object(), tools=[name])}
    )
    try:
        async with Client(server) as client:
            if profile == "raw":
                search = await client.call_tool("search_raw_tools", {"pattern": "^" + name + r"\b"})
                schema = json.loads(search.content[0].text)[0]["outputSchema"]
                assert schema["properties"]["columns"]["items"]["properties"]["workflow_guidance"]
            result = await client.call_tool(
                "call_raw_tool" if profile == "raw" else name,
                {"name": name, "arguments": {"order": 0}} if profile == "raw" else {"order": 0},
                raise_on_error=False,
            )
            assert len(effects) == 1
            if malformed and profile == "raw":
                assert result.is_error
                assert result.meta["mutation_receipt"]["outcome"] == "unknown"
                assert result.meta["mutation_receipt"]["retryable"] is False
            else:
                assert not result.is_error
                if not malformed:
                    assert result.structured_content == TypeAdapter(dict).dump_python(expected, mode="json")
                assert len(result.structured_content["columns"]) == 1
    finally:
        mcp_auth_context.reset(token)
