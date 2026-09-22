import asyncio
from threading import Event
from unittest.mock import Mock
import orjson
import pytest
import requests
from langboard.middlewares.CollaborativeEditMiddleware import CollaborativeEditMiddleware
from langboard_shared.core.routing import ApiPermission, SocketTopic
from langboard_shared.core.routing.ApiSchemaHelper import ApiSchemaMap
from langboard_shared.core.types import SafeDateTime
from langboard_shared.domain.models import User
from pytest import MonkeyPatch
from starlette.datastructures import Headers
from starlette.types import Message, Receive, Scope, Send


DOCUMENT_NAME = "card:example:title"
TEST_API_SCHEMA: ApiSchemaMap = {
    "name": "patch_card",
    "path": "/cards/example",
    "path_params": [],
    "method": "PATCH",
    "permission": ApiPermission.Edit,
    "content_type": "application/json",
    "description": "",
    "form": None,
    "query": None,
    "file_field": None,
    "request_schema_source": None,
    "collaborative_edit_targets": [
        {"document_name": DOCUMENT_NAME, "type": "text", "form_field": "title", "patch_field": "title"}
    ],
}


@pytest.mark.asyncio
async def test_editor_round_trips_do_not_block_api_authorization_callbacks(monkeypatch: MonkeyPatch) -> None:
    loop = asyncio.get_running_loop()
    observed: list[str] = []

    def round_trip(stage: str) -> None:
        authorized = Event()
        loop.call_soon_threadsafe(authorized.set)
        assert authorized.wait(1), f"The {stage} blocked the API event loop"
        observed.append(stage)

    def guard(headers: Headers, request: object, schema: object) -> None:
        round_trip("guard")

    def cleanup(headers: Headers, request: object, schema: object) -> None:
        round_trip("cleanup")

    async def downstream(scope: Scope, receive: Receive, send: Send) -> None:
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"{}"})

    async def receive() -> Message:
        return {"type": "http.request", "body": b'{"title":"Updated"}', "more_body": False}

    async def send(message: Message) -> None:
        pass

    middleware = CollaborativeEditMiddleware(downstream)
    monkeypatch.setattr(middleware, "_get_api_schema_by_path", lambda method, path: (TEST_API_SCHEMA, {}))
    monkeypatch.setitem(
        CollaborativeEditMiddleware.__call__.__globals__,
        "get_agent_allowed_permissions",
        lambda headers, default_read: {ApiPermission.Edit.value},
    )
    monkeypatch.setattr(middleware, "_get_collaborative_edit_guard_response", guard)
    monkeypatch.setattr(middleware, "_clear_inactive_collaborative_documents", cleanup)
    await middleware(
        {
            "type": "http",
            "method": "PATCH",
            "path": "/cards/example",
            "query_string": b"",
            "headers": [(b"x-api-token", b"test-token")],
        },
        receive,
        send,
    )
    assert observed == ["guard", "cleanup"]


@pytest.mark.parametrize("failure", ["network", "status", "json", "shape"])
def test_active_document_lookup_failure_is_not_an_empty_result(monkeypatch: MonkeyPatch, failure: str) -> None:
    def post(*args: object, **kwargs: object) -> Mock:
        if failure == "network":
            raise requests.ConnectionError("socket unavailable")

        response = Mock()
        response.status_code = 503 if failure == "status" else 200
        if failure == "json":
            response.json.side_effect = ValueError("invalid json")
        else:
            response.json.return_value = {} if failure == "shape" else {"active_document_names": []}
        return response

    monkeypatch.setattr(requests, "post", post)
    headers = Headers(raw=[(b"x-api-token", b"test-token")])

    assert CollaborativeEditMiddleware._get_active_collaborative_document_names(headers, [DOCUMENT_NAME]) is None


def test_active_document_lookup_keeps_a_valid_empty_result(monkeypatch: MonkeyPatch) -> None:
    response = Mock(status_code=200)
    response.json.return_value = {"active_document_names": []}
    monkeypatch.setattr(requests, "post", Mock(return_value=response))

    headers = Headers(raw=[(b"x-api-token", b"test-token")])
    assert CollaborativeEditMiddleware._get_active_collaborative_document_names(headers, [DOCUMENT_NAME]) == []


@pytest.mark.parametrize(("active_names", "expected_status"), [(None, 503), ([], 200)])
@pytest.mark.asyncio
async def test_active_lookup_controls_the_underlying_write(
    monkeypatch: MonkeyPatch, active_names: list[str] | None, expected_status: int
) -> None:
    called = False

    async def downstream(scope: Scope, receive: Receive, send: Send) -> None:
        nonlocal called
        called = True
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"{}"})

    middleware = CollaborativeEditMiddleware(downstream)
    monkeypatch.setattr(middleware, "_get_api_schema_by_path", lambda method, path: (TEST_API_SCHEMA, {}))
    monkeypatch.setitem(
        CollaborativeEditMiddleware.__call__.__globals__,
        "get_agent_allowed_permissions",
        lambda headers, default_read: {ApiPermission.Edit.value},
    )
    monkeypatch.setattr(middleware, "_get_active_collaborative_document_names", lambda headers, names: active_names)
    monkeypatch.setattr(middleware, "_clear_inactive_collaborative_documents", lambda headers, request, schema: None)

    async def receive() -> Message:
        return {"type": "http.request", "body": b'{"title":"Updated"}', "more_body": False}

    messages: list[Message] = []

    async def send(message: Message) -> None:
        messages.append(message)

    scope: Scope = {
        "type": "http",
        "method": "PATCH",
        "path": "/cards/example",
        "query_string": b"",
        "headers": [(b"x-api-token", b"test-token")],
    }

    await middleware(scope, receive, send)

    assert called is (expected_status == 200)
    assert (
        next(message["status"] for message in messages if message["type"] == "http.response.start") == expected_status
    )
    if expected_status == 503:
        body = b"".join(message.get("body", b"") for message in messages if message["type"] == "http.response.body")
        assert orjson.loads(body) == {"message": "Unable to verify active collaborative documents."}


def test_cleanup_does_not_clear_documents_when_active_lookup_fails(monkeypatch: MonkeyPatch) -> None:
    middleware = CollaborativeEditMiddleware(Mock())
    monkeypatch.setattr(
        middleware, "_get_requested_collaborative_document_names", lambda request, schema: [DOCUMENT_NAME]
    )
    monkeypatch.setattr(middleware, "_get_active_collaborative_document_names", lambda headers, names: None)
    post = Mock()
    monkeypatch.setattr(requests, "post", post)

    middleware._clear_inactive_collaborative_documents(
        Headers(raw=[(b"x-api-token", b"test-token")]),
        Mock(),
        TEST_API_SCHEMA,
    )

    post.assert_not_called()


def test_rich_patch_from_middleware_waits_for_the_document_owner(monkeypatch: MonkeyPatch) -> None:
    user = User.model_construct(activated_at=SafeDateTime.now(), deleted_at=None)
    service = Mock()
    owner_patch = Mock(return_value=None)
    authorize = Mock(return_value=(SocketTopic.BoardCard, "card-uid"))
    globals_map = CollaborativeEditMiddleware._patch_collaborative_documents.__globals__
    monkeypatch.setattr(globals_map["Auth"], "validate_user_by_api_token", lambda headers: user)
    monkeypatch.setitem(globals_map, "DomainService", lambda: service)
    monkeypatch.setitem(globals_map, "authorized_editor_document_subscription", authorize)
    monkeypatch.setattr(CollaborativeEditMiddleware, "_patch_collaborative_document", owner_patch)
    patch = {"document_name": "card:card-uid:description", "value": "New draft"}

    response = CollaborativeEditMiddleware._patch_collaborative_documents(
        Headers(raw=[(b"x-api-token", b"test-token")]), [], [patch]
    )

    assert response is None
    authorize.assert_called_once_with(service, user, patch["document_name"])
    owner_patch.assert_called_once_with("/editor-sync/rich/patch-request", patch, {"X-Api-Token": "test-token"})
    service.close.assert_called_once()


def test_rich_patch_denial_prevents_all_patches(monkeypatch: MonkeyPatch) -> None:
    user = User.model_construct(activated_at=SafeDateTime.now(), deleted_at=None)
    service = Mock()
    publish = Mock()
    globals_map = CollaborativeEditMiddleware._patch_collaborative_documents.__globals__
    monkeypatch.setattr(globals_map["Auth"], "validate_user_by_api_token", lambda headers: user)
    monkeypatch.setitem(globals_map, "DomainService", lambda: service)
    monkeypatch.setitem(
        globals_map,
        "authorized_editor_document_subscription",
        lambda service, user, name: (SocketTopic.BoardCard, "allowed") if name == "card:allowed:description" else None,
    )
    monkeypatch.setattr(CollaborativeEditMiddleware, "_patch_collaborative_document", publish)

    response = CollaborativeEditMiddleware._patch_collaborative_documents(
        Headers(raw=[(b"x-api-token", b"test-token")]),
        [],
        [
            {"document_name": "card:allowed:description", "value": "First"},
            {"document_name": "card:denied:description", "value": "Second"},
        ],
    )

    assert response == {"status": 403, "body": {"message": "Permission denied for editor sync patch."}}
    publish.assert_not_called()
    service.close.assert_called_once()


def test_rich_patch_rejects_oversized_payload_before_authentication(monkeypatch: MonkeyPatch) -> None:
    globals_map = CollaborativeEditMiddleware._patch_collaborative_documents.__globals__
    authenticate = Mock()
    monkeypatch.setattr(globals_map["Auth"], "validate_user_by_api_token", authenticate)
    monkeypatch.setitem(globals_map, "rich_patch_request_fits_limit", lambda name, value: False)

    response = CollaborativeEditMiddleware._patch_collaborative_documents(
        Headers(raw=[(b"x-api-token", b"test-token")]),
        [],
        [{"document_name": "card:card-uid:description", "value": "Too large"}],
    )

    assert response is not None and response["status"] == 413
    authenticate.assert_not_called()


@pytest.mark.parametrize("status_code", [409, 503, 504])
def test_rich_patch_owner_failure_is_not_acknowledged(monkeypatch: MonkeyPatch, status_code: int) -> None:
    user = User.model_construct(activated_at=SafeDateTime.now(), deleted_at=None)
    globals_map = CollaborativeEditMiddleware._patch_collaborative_documents.__globals__
    monkeypatch.setattr(globals_map["Auth"], "validate_user_by_api_token", lambda headers: user)
    monkeypatch.setitem(globals_map, "DomainService", Mock)
    monkeypatch.setitem(
        globals_map,
        "authorized_editor_document_subscription",
        lambda service, user, name: (SocketTopic.BoardCard, "card-uid"),
    )
    failure = {"status": status_code, "body": {"message": "Not applied"}}
    monkeypatch.setattr(CollaborativeEditMiddleware, "_patch_collaborative_document", Mock(return_value=failure))

    response = CollaborativeEditMiddleware._patch_collaborative_documents(
        Headers(raw=[(b"x-api-token", b"test-token")]),
        [],
        [{"document_name": "card:card-uid:description", "value": "New draft"}],
    )

    assert response == failure


def test_text_patch_still_uses_the_editor_owner(monkeypatch: MonkeyPatch) -> None:
    node_patch = Mock(return_value=None)
    monkeypatch.setattr(CollaborativeEditMiddleware, "_patch_collaborative_document", node_patch)
    patch = {"document_name": DOCUMENT_NAME, "field": "title", "value": "New title"}
    headers = Headers(raw=[(b"x-api-token", b"test-token")])

    response = CollaborativeEditMiddleware._patch_collaborative_documents(headers, [patch], [])

    assert response is None
    node_patch.assert_called_once_with("/editor-sync/text/patch", patch, {"X-Api-Token": "test-token"})


@pytest.mark.asyncio
async def test_active_rich_field_is_patched_without_a_regular_api_write(monkeypatch: MonkeyPatch) -> None:
    document_name = "card:card-uid:description"
    rich_schema: ApiSchemaMap = {
        **TEST_API_SCHEMA,
        "collaborative_edit_targets": [{"document_name": document_name, "type": "rich", "form_field": "description"}],
    }
    downstream = Mock()
    middleware = CollaborativeEditMiddleware(downstream)
    monkeypatch.setattr(middleware, "_get_api_schema_by_path", lambda method, path: (rich_schema, {}))
    monkeypatch.setitem(
        CollaborativeEditMiddleware.__call__.__globals__,
        "get_agent_allowed_permissions",
        lambda headers, default_read: {ApiPermission.Edit.value},
    )
    monkeypatch.setattr(middleware, "_get_active_collaborative_document_names", lambda headers, names: [document_name])
    user = User.model_construct(activated_at=SafeDateTime.now(), deleted_at=None)
    globals_map = CollaborativeEditMiddleware._patch_collaborative_documents.__globals__
    monkeypatch.setattr(globals_map["Auth"], "validate_user_by_api_token", lambda headers: user)
    monkeypatch.setitem(globals_map, "DomainService", Mock)
    monkeypatch.setitem(
        globals_map,
        "authorized_editor_document_subscription",
        lambda service, user, name: (SocketTopic.BoardCard, "card-uid"),
    )
    publish = Mock(return_value=None)
    monkeypatch.setattr(CollaborativeEditMiddleware, "_patch_collaborative_document", publish)
    scope: Scope = {
        "type": "http",
        "method": "PATCH",
        "path": "/cards/example",
        "query_string": b"",
        "headers": [(b"x-api-token", b"test-token")],
    }

    async def receive() -> Message:
        return {"type": "http.request", "body": b'{"description":{"content":"New draft"}}', "more_body": False}

    messages: list[Message] = []

    async def send(message: Message) -> None:
        messages.append(message)

    await middleware(scope, receive, send)

    downstream.assert_not_called()
    publish.assert_called_once_with(
        "/editor-sync/rich/patch-request",
        {"document_name": document_name, "value": "New draft"},
        {"X-Api-Token": "test-token"},
    )
    assert next(message["status"] for message in messages if message["type"] == "http.response.start") == 200
    body = b"".join(message.get("body", b"") for message in messages if message["type"] == "http.response.body")
    assert orjson.loads(body)["patched_rich_documents"] == [{"document_name": document_name, "value": "New draft"}]
