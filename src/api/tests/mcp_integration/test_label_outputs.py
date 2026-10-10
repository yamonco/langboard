"""Typed label transport preserves local-first selection and guarded creation."""

import json
from types import SimpleNamespace
import pytest
from fastmcp import Client
from langboard.mcp_integration.Server import McpServer
from langboard.mcp_integration.Tool import McpTool
from langboard.mcp_integration.WorkOutputs import WORK_OUTPUTS
from langboard.mcp_tools import CardMcp, LabelMcp
from langboard.middlewares.McpAuthMiddleware import mcp_auth_context
from langboard_shared.domain.models import GlobalLabel


@pytest.mark.parametrize("operation", ["catalog", "create", "global", "attach"])
async def test_real_label_handlers_through_modern_transport(monkeypatch, operation):
    local = [{"uid": "local", "name": "Request", "color": "#112233", "description": "x" * 1001}]
    current = [local[0]]
    writes = []
    global_label = GlobalLabel(id=123, name="Request", color="#445566", description="Global", emoji="🏷️")

    def create(actor, project, name, color, description):
        label = {"uid": "new", "name": name, "color": color, "description": description}
        local.append(label)
        writes.append("create")
        return object(), label

    def update(actor, project, card, uids):
        current[:] = [label for label in local if label["uid"] in uids]
        writes.append("labels")
        return True

    svc = SimpleNamespace(
        project=SimpleNamespace(get_by_id_like=lambda uid: object()),
        project_label=SimpleNamespace(
            get_api_list_by_project=lambda *args, **kwargs: local,
            get_api_list_by_card=lambda *args: current,
            create=create,
            use_global=lambda *args: {"label": local[0], "created": False, "global_label_uid": global_label.get_uid()},
        ),
        card=SimpleNamespace(update_labels=update),
    )
    monkeypatch.setattr(LabelMcp.InfraHelper, "get_all", lambda model: [global_label])
    monkeypatch.setattr(CardMcp, "_require_task_card", lambda *args: (object(), object()))

    if operation == "catalog":
        name, profile = "get_project_label_catalog", "agent"

        def handler(offset: int = 0):
            return LabelMcp.get_project_label_catalog("p", svc, offset=offset, limit=1)

        arguments = {}
    elif operation == "create":
        name, profile = "create_local_project_label", "raw"

        def handler(explicit_user_request: bool):
            return LabelMcp.create_local_project_label("p", "New", object(), svc, explicit_user_request)

        arguments = {"explicit_user_request": True}
    elif operation == "global":
        name, profile = "use_global_project_label", "raw"

        def handler():
            return LabelMcp.use_global_project_label("p", global_label.get_uid(), object(), svc)

        arguments = {}
    else:
        name, profile = "change_card_label", "raw"

        def handler(action: str):
            return LabelMcp.change_card_label("p", "c", "local", action, object(), svc)

        arguments = {"action": "detach"}

    metadata = {"handler": handler, "description": "Label", "exclude": [], "accessible_type": "all"}
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
            assert schema["additionalProperties"] is False

            async def invoke(args):
                return await client.call_tool(
                    "call_raw_tool" if profile == "raw" else name,
                    {"name": name, "arguments": args} if profile == "raw" else args,
                    raise_on_error=False,
                )

            if operation == "create":
                denied = await invoke({"explicit_user_request": False})
                assert denied.is_error
                assert not writes
                assert denied.meta["mutation_receipt"]["outcome"] == "unknown"
            result = await invoke(arguments)
            assert not result.is_error
            data = result.structured_content
            if operation == "catalog":
                assert data["items"][0]["source"] == "local"
                assert data["items"][0]["description_truncated"] is True
                assert data["next_offset"] == 1
                next_page = await invoke({"offset": 1})
                assert next_page.structured_content["items"][0]["source"] == "global"
                assert "mutation_receipt" not in (result.meta or {})
                assert not writes
            else:
                assert result.meta["mutation_receipt"]["outcome"] == "applied"
                again = await invoke(arguments)
                assert not again.is_error
                if operation == "create":
                    assert again.structured_content["created"] is False
                    assert writes == ["create"]
                elif operation == "global":
                    assert data["created"] is False
                    assert data["label"]["uid"] == "local"
                    assert data["global_label_uid"] == global_label.get_uid()
                    assert "global_label_uid" not in data["label"]
                    assert not writes
                else:
                    assert again.structured_content["changed"] is False
                    assert writes == ["labels"]
    finally:
        mcp_auth_context.reset(token)


def test_global_display_label_fields_remain_public_and_local_labels_have_no_emoji():
    from langboard.card_workspace.application.projections import public_label

    local = {
        "uid": "l",
        "name": "Request",
        "color": "#112233",
        "description": "d",
        "order": 0,
        "global_label_uid": None,
    }
    sourced = {
        **local,
        "global_label_uid": "g",
        "global_display": {"emoji": "🏷️", "translations": {"ko": {"name": "요청"}}},
    }
    for native in (local, sourced):
        projected = public_label(native)
        model = WORK_OUTPUTS["create_local_project_label"]
        assert (
            model.model_validate({"label": projected, "created": False}).model_dump(mode="json")["label"] == projected
        )
        assert "global_display" not in projected
    assert "emoji" not in public_label(local)
    assert public_label(sourced)["emoji"] == "🏷️"
