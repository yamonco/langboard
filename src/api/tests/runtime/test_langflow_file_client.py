from io import BytesIO
from typing import Any
from unittest.mock import Mock
import httpx
import pytest
from langboard_shared.ai.LangflowFileClient import LangflowFileClient
from langboard_shared.domain.models import InternalBot
from langboard_shared.Env import Env
from pytest import MonkeyPatch


def make_bot() -> InternalBot:
    return InternalBot.model_construct(api_url="https://langflow.example.test", api_key="server-key")


def test_upload_uses_server_credentials_and_preserves_file_identity(monkeypatch: MonkeyPatch) -> None:
    captured: dict[str, Any] = {}

    def post(url: str, **kwargs: object) -> httpx.Response:
        captured.update(url=url, kwargs=kwargs)
        return httpx.Response(
            201,
            json={"id": "file-id", "path": "user/file.txt"},
            request=httpx.Request("POST", url),
        )

    monkeypatch.setattr("langboard_shared.ai.LangflowFileClient.httpx.post", post)

    result = LangflowFileClient.upload(make_bot(), BytesIO(b"hello"), "file.txt", "text/plain", 5)

    assert result.file_id == "file-id"
    assert result.path == "user/file.txt"
    assert captured["url"] == "https://langflow.example.test/api/v2/files"
    assert captured["kwargs"]["headers"] == {"x-api-key": "server-key"}
    assert captured["kwargs"]["files"]["file"][0] == "file.txt"


@pytest.mark.parametrize("filename", ["../file.txt", "folder/file.txt", "folder\\file.txt", "file\x00.txt"])
def test_upload_rejects_unsafe_filename_before_network(monkeypatch: MonkeyPatch, filename: str) -> None:
    post = Mock()
    monkeypatch.setattr("langboard_shared.ai.LangflowFileClient.httpx.post", post)

    with pytest.raises(ValueError, match="filename is invalid"):
        LangflowFileClient.upload(make_bot(), BytesIO(b"hello"), filename, "text/plain", 5)

    post.assert_not_called()


@pytest.mark.parametrize("size", [0, -1, Env.MAX_FILE_SIZE_MB * 1024 * 1024 + 1])
def test_upload_rejects_invalid_size_before_network(monkeypatch: MonkeyPatch, size: int) -> None:
    post = Mock()
    monkeypatch.setattr("langboard_shared.ai.LangflowFileClient.httpx.post", post)

    with pytest.raises(ValueError, match="size is invalid"):
        LangflowFileClient.upload(make_bot(), BytesIO(b"hello"), "file.txt", "text/plain", size)

    post.assert_not_called()


def test_delete_uses_file_id_and_treats_not_found_as_reclaimed(monkeypatch: MonkeyPatch) -> None:
    captured: dict[str, Any] = {}

    def delete(url: str, **kwargs: object) -> httpx.Response:
        captured.update(url=url, kwargs=kwargs)
        return httpx.Response(404)

    monkeypatch.setattr("langboard_shared.ai.LangflowFileClient.httpx.delete", delete)

    assert LangflowFileClient.delete(make_bot(), "file/id")
    assert captured["url"] == "https://langflow.example.test/api/v2/files/file%2Fid"
    assert captured["kwargs"]["headers"] == {"x-api-key": "server-key"}
