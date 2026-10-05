"""Native image results retain card ancestry, content boundaries and budgets."""

from types import SimpleNamespace
import pytest
from fastmcp.tools import ToolResult
from langboard.mcp_integration.ResponseBudget import ReadResponseBudgetMiddleware
from langboard.mcp_tools import CardImagesMcp as images
from mcp.types import ImageContent


@pytest.fixture
def image_card(monkeypatch):
    monkeypatch.setattr(
        images, "Env", SimpleNamespace(PUBLIC_UI_URL="https://board.example", API_URL="https://board.example/api")
    )
    monkeypatch.setattr(images, "_get_card_in_project", lambda *args: (object(), SimpleNamespace(id=1)))
    rows = {
        "valid": SimpleNamespace(card_id=1, file=SimpleNamespace(path="/file/key/card_attachment/a.png")),
        "foreign": SimpleNamespace(card_id=2),
    }
    service = SimpleNamespace(
        card=SimpleNamespace(get_details=lambda *args: {"description": "![body](/api/file/key/card_attachment/a.png)"}),
        card_attachment=SimpleNamespace(get_by_id_like=rows.get),
    )
    calls = []

    def download(storage, name, filename, destination):
        calls.append((storage, name, filename))
        destination.write(b"\x89PNG\r\n\x1a\nfixture")
        return True

    monkeypatch.setattr(images.Storage, "download", download)
    return service, calls


def test_native_images_return_content_deduplicate_and_reject_foreign_attachment(image_card):
    service, calls = image_card
    result = images.read_card_images("project", "card", object(), service, ["valid", "foreign", "missing"])
    assert [block.type for block in result.content] == ["text", "image"]
    assert result.content[1].mime_type == "image/png"
    assert calls == [("key", "card_attachment", "a.png")]
    assert len(result.structured_content["omitted"]) == 2
    assert result.structured_content["total_bytes"] == 15


def test_attachment_only_does_not_read_body_image(image_card):
    service, calls = image_card
    result = images.read_card_images("project", "card", object(), service, [], False)
    assert result.structured_content["included"] == [] and calls == []


@pytest.mark.parametrize(
    "url",
    [
        "https://foreign.example/file/key/card_attachment/a.png",
        "file:///etc/passwd",
        "/file/key/card_attachment/../secret",
        "/file/key/card_attachment/%2e%2e",
        "/file/key/avatar/a.png",
        "/file/key/card_attachment/a.png?token=x",
    ],
)
def test_body_source_cannot_fetch_arbitrary_url_or_traverse_storage(image_card, url):
    assert images._stored_image_path(url) is None


def test_editor_parser_ignores_code_and_links():
    assert images._image_urls("`![code](/file/a)`\n[link](/file/b)\n![image](/file/c)") == ["/file/c"]
    assert images._image_urls({"children": [{"type": "img", "url": "/file/a"}]}) == ["/file/a"]
    assert images._image_urls('{"content":"[{\\"type\\":\\"img\\",\\"url\\":\\"/file/a\\"}]"}') == ["/file/a"]


def test_count_and_byte_limits_report_omission(image_card, monkeypatch):
    service, calls = image_card
    service.card.get_details = lambda *args: {
        "description": "![a](/file/key/card_attachment/a.png) ![b](/file/key/card_attachment/b.png)"
    }
    monkeypatch.setattr(images, "MAX_IMAGES", 1)
    result = images.read_card_images("p", "c", object(), service)
    assert result.structured_content["omitted"][0]["reason"] == "image_count_limit"
    assert len(calls) == 1
    monkeypatch.setattr(images, "MAX_TOTAL_BYTES", 4)
    result = images.read_card_images("p", "c", object(), service)
    assert {entry["reason"] for entry in result.structured_content["omitted"]} == {"byte_limit"}
    assert result.structured_content["total_bytes"] == 0


async def test_image_budget_preserves_multimodal_content_but_keeps_plain_reads_bounded():
    result = ToolResult(content=[ImageContent(type="image", data="A" * 1_100_000, mime_type="image/png")])

    async def next_call(context):
        return result

    middleware = ReadResponseBudgetMiddleware()
    image_context = SimpleNamespace(message=SimpleNamespace(name="read_card_images"))
    assert await middleware.on_call_tool(image_context, next_call) is result
    plain_context = SimpleNamespace(message=SimpleNamespace(name="read_card_attachment"))
    assert (await middleware.on_call_tool(plain_context, next_call)).is_error
