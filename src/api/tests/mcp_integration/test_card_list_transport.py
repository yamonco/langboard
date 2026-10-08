import pytest
from fastmcp import Client, FastMCP
from langboard.card_workspace.application.dtos import ProjectCardIndexResponse, ProjectCardListResponse
from langboard.mcp_integration.Providers import create_native_tool


@pytest.mark.parametrize("modern", [False, True])
async def test_tree_survives_fastmcp_output_serialization(modern):
    async def handler(project_uid: str, format: str = "tree") -> ProjectCardListResponse:
        return ProjectCardIndexResponse.model_validate(
            {
                "project_uid": project_uid,
                "cards": {
                    "items": [{"uid": "a", "children": [{"uid": "b", "children": []}]}],
                    "total_count": 2,
                    "next_cursor": None,
                    "limit": 20,
                },
                "workflow_stages": {},
                "columns": {},
                "format": "tree",
                "relationships": [{"parent_card_uid": "a", "child_card_uid": "b", "machine_semantic": "contains"}],
                "relationship_scope": "current_page",
                "relationships_truncated": False,
            }
        )

    server = FastMCP("transport-proof")
    server.add_tool(
        create_native_tool(
            "list_project_cards",
            {"handler": handler, "description": "List cards"},
            lambda name, fn: fn,
            modern_annotations=modern,
        )
    )
    async with Client(server) as client:
        result = await client.call_tool("list_project_cards", {"project_uid": "board"})
        assert result.structured_content["format"] == "tree"
        assert result.structured_content["relationship_scope"] == "current_page"
        assert result.structured_content["cards"]["items"][0]["children"][0]["uid"] == "b"
