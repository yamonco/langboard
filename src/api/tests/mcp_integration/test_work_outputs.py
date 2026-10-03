"""Native projections and pagination must survive typed transport serialization."""

import json
from types import SimpleNamespace
import pytest
from fastmcp import Client
from langboard.card_workspace.application.projections import public_checklist
from langboard.mcp_integration.Server import McpServer
from langboard.mcp_integration.Tool import McpTool
from langboard.middlewares.McpAuthMiddleware import mcp_auth_context


@pytest.mark.parametrize("profile", ["agent", "raw", "compatibility"])
@pytest.mark.parametrize("malformed", [False, True])
async def test_nested_work_output_omission_pagination_and_unknown_after_write(monkeypatch, profile, malformed):
    from langboard.card_workspace.application.projections import bounded_items

    name = "update_card_checklist" if profile == "raw" else "update_card_checkitem"
    projected = public_checklist(
        {
            "uid": "list",
            "title": "Tasks",
            "is_checked": False,
            "checkitems": [{"uid": str(i), "title": "t" * 1001, "deadline_at": None} for i in range(30)],
        }
    )
    if malformed:
        projected["checkitems"][0]["uid"] = 1
    payload = {"checklists": bounded_items([projected], "checklists", 25)}
    expected = {"checklists": payload["checklists"].model_dump()}
    effects = []

    def command(value: int) -> dict:
        effects.append(value)
        return payload

    metadata = {"handler": command, "description": "Update checklist", "exclude": [], "accessible_type": "all"}
    monkeypatch.setattr(McpTool, "get_tools", lambda: {name: metadata})
    monkeypatch.setattr(McpTool, "get_tool", lambda tool_name: metadata if tool_name == name else None)
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
            else:
                schema = (await client.list_tools())[0].output_schema
            if profile != "compatibility":
                page = schema["properties"]["checklists"]
                nested = page["properties"]["items"]["items"]["properties"]["checkitems"]["items"]
                assert nested["properties"]["uid"]["type"] == "string"
                assert page["properties"]["next_cursor"]
            result = await client.call_tool(
                "call_raw_tool" if profile == "raw" else name,
                {"name": name, "arguments": {"value": 1}} if profile == "raw" else {"value": 1},
                raise_on_error=False,
            )
            assert effects == [1]
            if malformed and profile != "compatibility":
                assert result.is_error
                assert result.meta["mutation_receipt"]["outcome"] == "unknown"
                assert result.meta["mutation_receipt"]["retryable"] is False
            else:
                assert not result.is_error
                assert result.structured_content == expected
                item = result.structured_content["checklists"]["items"][0]
                assert item["checkitems_next_cursor"]
                assert item["checkitems"][0]["deadline_at"] is None
                assert "updated_at" not in item["checkitems"][0]
                assert item["checkitems"][0]["title_truncated"] is True
    finally:
        mcp_auth_context.reset(token)


def test_real_native_models_preserve_dates_and_comment_fields():
    from typing import Any
    from langboard.card_workspace.application.projections import public_checkitem, public_comment
    from langboard.mcp_integration.WorkOutputs import CheckitemOutput, ChecklistOutput, CommentOutput
    from langboard_shared.core.db import EditorContentModel
    from langboard_shared.core.types import SafeDateTime
    from langboard_shared.domain.models import CardComment, Checkitem, Checklist
    from pydantic import TypeAdapter

    now = SafeDateTime.now()
    checklist = Checklist(id=123, card_id=456, title="t" * 1001, created_at=now, updated_at=now)
    item = Checkitem(id=789, checklist_id=123, title="Task", created_at=now, updated_at=now)
    comment = CardComment(
        id=101, card_id=456, content=EditorContentModel(content="한글 댓글"), created_at=now, updated_at=now
    )
    for projection, model in [
        (public_checklist({**checklist.api_response(), "checkitems": [item.api_response()]}), ChecklistOutput),
        (public_checkitem(item.api_response()), CheckitemOutput),
        (public_comment(comment.api_response()), CommentOutput),
    ]:
        assert model.model_validate(projection).model_dump(mode="json") == TypeAdapter(dict[str, Any]).dump_python(
            projection, mode="json"
        )
