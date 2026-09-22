from collections.abc import Iterator
from unittest.mock import Mock
from fastapi import Request
from langboard.middlewares.CollaborativeEditMiddleware import CollaborativeEditMiddleware
from langboard.routes.editor import EditorSyncApi
from langboard_shared.Env import Env
from pytest import MonkeyPatch, fixture


@fixture
def editor_ingress() -> Iterator[None]:
    previous = Env.SOCKET_EDITOR_INTERNAL_URL
    Env.update_env("SOCKET_EDITOR_INTERNAL_URL", "http://editor-ingress.example.invalid")
    try:
        yield
    finally:
        Env.update_env("SOCKET_EDITOR_INTERNAL_URL", previous)


def test_editor_api_forwards_to_the_shared_editor_ingress(monkeypatch: MonkeyPatch, editor_ingress: None) -> None:
    post = Mock(return_value=Mock(status_code=200, json=Mock(return_value={"active_document_names": []})))
    monkeypatch.setattr(EditorSyncApi.requests, "post", post)

    response = EditorSyncApi._forward_to_socket(
        Request({"type": "http", "headers": []}), "/editor-sync/active", {"document_names": []}
    )

    assert response.status_code == 200
    assert post.call_args.args[0] == "http://editor-ingress.example.invalid/editor-sync/active"


def test_batch_editor_patch_uses_the_same_ingress(monkeypatch: MonkeyPatch, editor_ingress: None) -> None:
    post = Mock(return_value=Mock(status_code=200))
    monkeypatch.setattr(EditorSyncApi.requests, "post", post)

    result = CollaborativeEditMiddleware._patch_collaborative_document(
        "/editor-sync/text/patch", {"document_name": "card:fixture:title", "field": "title", "value": "Draft"}, {}
    )

    assert result is None
    assert post.call_args.args[0] == "http://editor-ingress.example.invalid/editor-sync/text/patch"
