from collections.abc import Iterator
from unittest.mock import Mock
from fastapi import Request
from langboard.middlewares.CollaborativeEditMiddleware import CollaborativeEditMiddleware
from langboard.routes.editor import EditorSyncApi
from langboard_shared.core.routing import EDITOR_ROUTE_KEY_HEADER, create_editor_document_route_key
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
    assert post.call_args.kwargs["headers"][EDITOR_ROUTE_KEY_HEADER] == create_editor_document_route_key(
        "card:fixture:title"
    )


def test_single_document_api_forwards_the_same_route_key(monkeypatch: MonkeyPatch, editor_ingress: None) -> None:
    assert create_editor_document_route_key("card:fixture:description") == "b8342b48"
    post = Mock(return_value=Mock(status_code=200, json=Mock(return_value={"value": "Draft"})))
    monkeypatch.setattr(EditorSyncApi.requests, "post", post)

    response = EditorSyncApi._forward_to_socket(
        Request({"type": "http", "headers": []}),
        "/editor-sync/text",
        {"document_name": "card:fixture:description", "field": "description"},
    )

    assert response.status_code == 200
    assert post.call_args.kwargs["headers"][EDITOR_ROUTE_KEY_HEADER] == "b8342b48"


def test_active_documents_use_one_editor_request(monkeypatch: MonkeyPatch, editor_ingress: None) -> None:
    names = ["card:fixture:title", "card:fixture:description", "card:fixture:comments"]
    requests_seen: list[list[str]] = []

    def post(url: str, **kwargs: object) -> Mock:
        body = kwargs["json"]
        headers = kwargs["headers"]
        assert isinstance(body, dict) and isinstance(headers, dict)
        names = body["document_names"]
        assert isinstance(names, list)
        assert EDITOR_ROUTE_KEY_HEADER not in headers
        requests_seen.append(names)
        return Mock(status_code=200, json=Mock(return_value={"active_document_names": names}))

    monkeypatch.setattr(EditorSyncApi.requests, "post", post)
    active = CollaborativeEditMiddleware._get_active_collaborative_document_names(
        Request({"type": "http", "headers": [(b"x-api-token", b"test-token")]}).headers, names
    )

    assert active == names
    assert requests_seen == [names]


def test_active_document_lookup_fails_closed_when_editor_is_unavailable(
    monkeypatch: MonkeyPatch, editor_ingress: None
) -> None:
    monkeypatch.setattr(EditorSyncApi.requests, "post", Mock(return_value=Mock(status_code=503)))
    active = CollaborativeEditMiddleware._get_active_collaborative_document_names(
        Request({"type": "http", "headers": [(b"x-api-token", b"test-token")]}).headers,
        ["card:fixture:title", "card:fixture:description"],
    )

    assert active is None


def test_inactive_documents_use_one_clear_request(monkeypatch: MonkeyPatch, editor_ingress: None) -> None:
    names = ["card:fixture:title", "card:fixture:description"]
    clears: list[list[str]] = []

    def post(url: str, **kwargs: object) -> Mock:
        body = kwargs["json"]
        headers = kwargs["headers"]
        assert isinstance(body, dict) and isinstance(headers, dict)
        names = body["document_names"]
        assert isinstance(names, list)
        if url.endswith("/clear"):
            assert EDITOR_ROUTE_KEY_HEADER not in headers
            clears.append(names)
            return Mock(status_code=200)
        return Mock(status_code=200, json=Mock(return_value={"active_document_names": []}))

    monkeypatch.setattr(EditorSyncApi.requests, "post", post)
    middleware = CollaborativeEditMiddleware(Mock())
    monkeypatch.setattr(middleware, "_get_requested_collaborative_document_names", lambda request, schema: names)
    middleware._clear_inactive_collaborative_documents(
        Request({"type": "http", "headers": [(b"x-api-token", b"test-token")]}).headers,
        Mock(),
        Mock(),
    )

    assert clears == [names]
