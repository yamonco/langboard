"""Native resource projections retain pagination and access-filtered links."""

import json
from types import SimpleNamespace
import pytest
from fastmcp import Client
from langboard.card_workspace.application.projections import bounded_items, public_attachment
from langboard.card_workspace.infrastructure import linked_wikis
from langboard.mcp_integration.ResourceOutputs import RESOURCE_OUTPUTS
from langboard.mcp_integration.Server import McpServer
from langboard.mcp_integration.Tool import McpTool
from langboard.mcp_tools import CardMcp
from langboard.middlewares.McpAuthMiddleware import mcp_auth_context
from langboard_shared.core.storage import FileModel
from langboard_shared.domain.models import CardAttachment
from pydantic import TypeAdapter


def test_actual_upload_handler_preserves_native_file_response(monkeypatch):
    file = FileModel(
        storage_type="local",
        storage_name="card",
        original_filename="한글.txt",
        filename="stored.txt",
        path="/file/reference",
    )
    native = CardAttachment(id=123, user_id=456, card_id=789, filename=file.original_filename, file=file)
    monkeypatch.setattr(CardMcp, "_require_task_card", lambda *args: None)
    monkeypatch.setattr(CardMcp.Storage, "upload", lambda *args: file)
    service = SimpleNamespace(card_attachment=SimpleNamespace(create=lambda *args: native))
    expected = CardMcp.upload_card_attachment("board", "card", file.original_filename, "YQ==", object(), service)
    actual = RESOURCE_OUTPUTS["upload_card_attachment"].model_validate(expected).model_dump(mode="json")
    assert actual == TypeAdapter(dict).dump_python(expected, mode="json")
    assert actual["url"] == "/file/reference"
    assert "user" not in actual


def test_link_handler_retains_only_currently_readable_wikis(monkeypatch):
    project = SimpleNamespace(id=1)
    card = SimpleNamespace(is_linked_resource=False)
    visible = SimpleNamespace(project_id=1, title="Visible", get_uid=lambda: "visible")
    private = SimpleNamespace(project_id=1, title="Private", get_uid=lambda: "private")
    foreign = SimpleNamespace(project_id=2, title="Foreign", get_uid=lambda: "foreign")
    writes = []
    monkeypatch.setattr(linked_wikis, "User", SimpleNamespace)
    monkeypatch.setattr(CardMcp, "_require_task_card", lambda *args: (project, card))
    service = SimpleNamespace(
        metadata=SimpleNamespace(
            save=lambda *args: writes.append(args) or True,
            get_all_as_api=lambda *args, **kwargs: {
                "linked_wiki:visible": "1",
                "linked_wiki:private": "1",
                "linked_wiki:foreign": "1",
            },
        ),
        project_wiki=SimpleNamespace(
            get_by_id_like=lambda uid: {"visible": visible, "private": private, "foreign": foreign}[uid],
            is_assigned=lambda user, wiki: wiki is visible,
        ),
    )
    expected = CardMcp.update_card_linked_wiki("board", "card", "visible", "link", SimpleNamespace(), service)
    assert RESOURCE_OUTPUTS["update_card_linked_wiki"].model_validate(expected).model_dump(mode="json") == expected
    assert expected["linked_wikis"] == [{"wiki_uid": "visible", "title": "Visible"}]
    assert len(writes) == 1
    with pytest.raises(ValueError, match="access denied"):
        CardMcp.update_card_linked_wiki("board", "card", "private", "link", SimpleNamespace(), service)
    assert len(writes) == 1


def test_card_to_wiki_handler_retains_explicit_archive_choice(monkeypatch):
    project = SimpleNamespace(id=1)
    card = SimpleNamespace(title="Card", description=SimpleNamespace(content="Body"))
    wiki = SimpleNamespace(title="Card", get_uid=lambda: "wiki")
    archives = []
    monkeypatch.setattr(CardMcp, "_require_task_card", lambda *args: (project, card))
    monkeypatch.setattr(CardMcp, "change_link", lambda *args: [{"wiki_uid": "wiki", "title": "Card"}])
    service = SimpleNamespace(
        project=SimpleNamespace(get_user_role_actions_by_project=lambda *args: ["*"]),
        project_wiki=SimpleNamespace(create=lambda *args: (wiki, {})),
        card=SimpleNamespace(archive=lambda *args: archives.append(args)),
    )
    expected = CardMcp.create_wiki_from_card(
        "board", "card", object(), service, include_checklists=False, include_attachments_as_references=False
    )
    assert RESOURCE_OUTPUTS["create_wiki_from_card"].model_validate(expected).model_dump(mode="json") == expected
    assert expected["card_archived"] is False and not archives


@pytest.mark.parametrize("profile", ["raw", "compatibility"])
@pytest.mark.parametrize("malformed", [False, True])
async def test_public_attachment_page_privacy_and_postsave_outcome(monkeypatch, profile, malformed):
    items = [
        public_attachment(
            {
                "uid": str(i),
                "name": "n" * 1001,
                "url": "private-storage",
                "user": {"uid": "actor", "firstname": "u" * 1001, "email": "private", "avatar": None},
            }
        )
        for i in range(26)
    ]
    payload = {"attachments": bounded_items(items, "attachments", 25)}
    if malformed:
        payload["attachments"].items[0]["user"]["uid"] = 1
    effects = []

    def handler(value: int) -> dict:
        effects.append(value)
        return payload

    name = "update_card_attachment"
    metadata = {"handler": handler, "description": "Update attachment", "exclude": [], "accessible_type": "all"}
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
                item = json.loads(search.content[0].text)[0]["outputSchema"]["properties"]["attachments"]["properties"][
                    "items"
                ]["items"]
                assert "url" not in item["properties"]
            result = await client.call_tool(
                "call_raw_tool" if profile == "raw" else name,
                {"name": name, "arguments": {"value": 1}} if profile == "raw" else {"value": 1},
                raise_on_error=False,
            )
            assert effects == [1]
            if malformed and profile == "raw":
                assert result.is_error
                assert result.meta["mutation_receipt"]["outcome"] == "unknown"
                assert result.meta["mutation_receipt"]["retryable"] is False
            else:
                assert not result.is_error
                page = result.structured_content["attachments"]
                assert len(page["items"]) == 25 and page["next_cursor"]
                assert "url" not in page["items"][0]
                assert "email" not in page["items"][0]["user"]
                assert page["items"][0]["user"]["firstname_truncated"] is True
                assert page["items"][0]["user"]["avatar"] is None
    finally:
        mcp_auth_context.reset(token)
