from enum import Enum
from json import dumps as json_dumps
from json import loads as json_loads
from string import Formatter
from typing import cast
from urllib.parse import parse_qsl
import requests
from fastapi import status
from langboard_shared.core.routing import AppRouter, JsonResponse
from langboard_shared.core.routing.ApiSchemaHelper import ApiSchemaMap
from langboard_shared.core.security import AuthSecurity
from langboard_shared.core.utils.Converter import json_default
from langboard_shared.Env import Env
from langboard_shared.helpers.AgentApiPermissionHelper import (
    create_permission_denied_response,
    get_agent_allowed_permissions,
    has_agent_api_token,
)
from starlette.datastructures import Headers
from starlette.types import ASGIApp, Message, Receive, Scope, Send
from ..routes.batcher.BatchForm import BatchFormRequestSchema


class CollaborativeEditMiddleware:
    __auto_load__ = False

    WRITE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        method = str(scope.get("method", "")).upper()
        if method not in self.WRITE_METHODS:
            await self.app(scope, receive, send)
            return

        headers = Headers(scope=scope)
        if not has_agent_api_token(headers):
            await self.app(scope, receive, send)
            return

        request_path = str(scope.get("path", ""))
        api_schema = cast(ApiSchemaMap | None, scope.get("batch_api_schema"))
        path_params: dict[str, str] = {}
        if api_schema:
            path_params = self._match_api_path(api_schema["path"], request_path) or {}
        else:
            api_schema, path_params = self._get_api_schema_by_path(method, request_path)

        if not api_schema or api_schema["path"] == "/batch":
            await self.app(scope, receive, send)
            return

        allowed_permissions = get_agent_allowed_permissions(headers, default_read=True) or set()
        permission = self._get_api_permission_value(api_schema)
        if permission not in allowed_permissions:
            content, status_code = create_permission_denied_response()
            response = JsonResponse(
                content=content,
                status_code=status_code,
            )
            await response(scope, receive, send)
            return

        try:
            body, disconnected = await self._read_body(receive)
        except ValueError as error:
            response = JsonResponse(
                content={"message": str(error)},
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            )
            await response(scope, receive, send)
            return

        body_messages = cast(
            list[Message],
            [{"type": "http.request", "body": body, "more_body": False}],
        )
        if disconnected:
            body_messages.append({"type": "http.disconnect"})
        request_schema = BatchFormRequestSchema(
            path_or_api_name=request_path,
            method=method,
            query={**dict(parse_qsl(scope.get("query_string", b"").decode())), **path_params},
            form=self._parse_json_body(body),
        )

        guard_response = self._get_collaborative_edit_guard_response(headers, request_schema, api_schema)
        if guard_response is not None:
            response = JsonResponse(
                content=guard_response.get("body", {}),
                status_code=guard_response.get("status", status.HTTP_200_OK),
            )
            await response(scope, self._replay_body_messages(body_messages), send)
            return

        if request_schema.form is not None:
            body_messages = cast(
                list[Message],
                [
                    {
                        "type": "http.request",
                        "body": json_dumps(request_schema.form, default=json_default).encode(),
                        "more_body": False,
                    }
                ],
            )

        response_status_code: int | None = None

        async def capture_send(message: Message):
            nonlocal response_status_code
            if message.get("type") == "http.response.start":
                response_status_code = message.get("status", status.HTTP_200_OK)
            await send(message)

        await self.app(scope, self._replay_body_messages(body_messages), capture_send)

        if response_status_code is not None and status.HTTP_200_OK <= response_status_code < 300:
            self._clear_inactive_collaborative_documents(headers, request_schema, api_schema)

    @staticmethod
    def _get_api_schema_by_path(method: str, request_path: str) -> tuple[ApiSchemaMap | None, dict[str, str]]:
        for schema in AppRouter.api_routes.values():
            if schema["method"].upper() != method.upper():
                continue
            path_params = CollaborativeEditMiddleware._match_api_path(schema["path"], request_path)
            if path_params is not None:
                return schema, path_params

        return None, {}

    @staticmethod
    def _get_api_permission_value(api_schema: ApiSchemaMap) -> str:
        permission = api_schema["permission"]
        return permission.value if isinstance(permission, Enum) else permission

    def _get_collaborative_edit_guard_response(
        self, headers: Headers, request_schema: BatchFormRequestSchema, api_schema: ApiSchemaMap
    ) -> dict | None:
        targets = self._get_collaborative_edit_targets(request_schema, api_schema)
        document_names = [target["document_name"] for target in targets]
        active_document_names = self._get_active_collaborative_document_names(headers, document_names)
        if not active_document_names:
            return None

        text_patch_payloads = self._get_collaborative_text_patch_payloads(request_schema, targets)
        active_text_patch_payloads = [
            patch_payload
            for patch_payload in text_patch_payloads
            if patch_payload["document_name"] in active_document_names
        ]
        rich_patch_payloads = self._get_collaborative_rich_patch_payloads(request_schema, targets)
        active_rich_patch_payloads = [
            patch_payload
            for patch_payload in rich_patch_payloads
            if patch_payload["document_name"] in active_document_names
        ]
        patched_document_names = {patch_payload["document_name"] for patch_payload in active_text_patch_payloads}
        patched_document_names.update(patch_payload["document_name"] for patch_payload in active_rich_patch_payloads)
        unsupported_active_document_names = [
            document_name for document_name in active_document_names if document_name not in patched_document_names
        ]

        if (active_text_patch_payloads or active_rich_patch_payloads) and not unsupported_active_document_names:
            patch_response = self._patch_collaborative_documents(
                headers, active_text_patch_payloads, active_rich_patch_payloads
            )
            if patch_response is not None:
                return patch_response

            if self._remove_patched_collaborative_fields(request_schema, api_schema, targets, patched_document_names):
                return None

            return self._batch_response(
                {
                    "draft_updated": True,
                    "active_documents": active_document_names,
                    "patched_documents": active_text_patch_payloads,
                    "patched_rich_documents": active_rich_patch_payloads,
                }
            )

        return self._batch_response(
            {
                "message": (
                    "The target is currently being edited in real time and cannot be safely updated through this API."
                ),
                "active_documents": active_document_names,
                "active_text_documents": [
                    {"document_name": patch_payload["document_name"], "field": patch_payload["field"]}
                    for patch_payload in active_text_patch_payloads
                ],
                "active_rich_documents": [
                    {"document_name": patch_payload["document_name"]} for patch_payload in active_rich_patch_payloads
                ],
            },
            status.HTTP_409_CONFLICT,
        )

    @staticmethod
    def _get_collaborative_edit_targets(
        request_schema: BatchFormRequestSchema, api_schema: ApiSchemaMap
    ) -> list[dict[str, str]]:
        request_params = {**(request_schema.form or {}), **(request_schema.query or {})}
        targets: list[dict[str, str]] = []
        for target in api_schema.get("collaborative_edit_targets", []):
            document_name = target.get("document_name")
            if not isinstance(document_name, str):
                continue

            target_type = target.get("type")
            if target_type not in {"text", "rich", "block"}:
                continue

            form_field = target.get("form_field")
            patch_field = target.get("patch_field")
            for formatted_document_name in CollaborativeEditMiddleware._format_collaborative_document_names(
                document_name, request_params
            ):
                targets.append(
                    {
                        "type": target_type,
                        "document_name": formatted_document_name,
                        "form_field": form_field if isinstance(form_field, str) else "",
                        "patch_field": patch_field if isinstance(patch_field, str) else "",
                    }
                )

        return targets

    @staticmethod
    def _format_collaborative_document_names(document_name: str, request_params: dict) -> list[str]:
        field_names = [
            field_name
            for _, field_name, _, _ in Formatter().parse(document_name)
            if field_name and field_name in request_params
        ]
        list_field_names = [field_name for field_name in field_names if isinstance(request_params[field_name], list)]

        if not list_field_names:
            try:
                return [document_name.format(**request_params)]
            except Exception:
                return []

        if len(list_field_names) > 1:
            return []

        list_field_name = list_field_names[0]
        document_names: list[str] = []
        for value in request_params[list_field_name]:
            if not isinstance(value, (str, int, float)):
                continue
            next_params = {**request_params, list_field_name: value}
            try:
                document_names.append(document_name.format(**next_params))
            except Exception:
                continue

        return document_names

    @staticmethod
    def _get_requested_collaborative_document_names(
        request_schema: BatchFormRequestSchema, api_schema: ApiSchemaMap
    ) -> list[str]:
        form = request_schema.form or {}
        document_names: list[str] = []
        for target in CollaborativeEditMiddleware._get_collaborative_edit_targets(request_schema, api_schema):
            if target["type"] != "block" and target["form_field"] not in form:
                continue
            if target["document_name"] in document_names:
                continue
            document_names.append(target["document_name"])

        return document_names

    def _clear_inactive_collaborative_documents(
        self, headers: Headers, request_schema: BatchFormRequestSchema, api_schema: ApiSchemaMap
    ) -> None:
        document_names = self._get_requested_collaborative_document_names(request_schema, api_schema)
        if not document_names:
            return

        active_document_names = set(self._get_active_collaborative_document_names(headers, document_names))
        inactive_document_names = [
            document_name for document_name in document_names if document_name not in active_document_names
        ]
        if not inactive_document_names:
            return

        request_headers = self._get_socket_request_headers(headers)
        if not request_headers:
            return

        try:
            requests.post(
                f"{Env.SOCKET_INTERNAL_URL}/editor-sync/clear",
                json={"document_names": inactive_document_names},
                headers=request_headers,
                timeout=10,
            )
        except requests.RequestException:
            return

    @staticmethod
    def _get_active_collaborative_document_names(headers: Headers, document_names: list[str]) -> list[str]:
        if not document_names:
            return []

        request_headers = CollaborativeEditMiddleware._get_socket_request_headers(headers)
        if not request_headers:
            return []

        try:
            response = requests.post(
                f"{Env.SOCKET_INTERNAL_URL}/editor-sync/active",
                json={"document_names": document_names},
                headers=request_headers,
                timeout=10,
            )
        except requests.RequestException:
            return []

        if not (status.HTTP_200_OK <= response.status_code < 300):
            return []

        try:
            content = response.json()
        except ValueError:
            return []

        active_document_names = content.get("active_document_names")
        if not isinstance(active_document_names, list):
            return []

        document_name_set = set(document_names)
        return [
            document_name
            for document_name in active_document_names
            if isinstance(document_name, str) and document_name in document_name_set
        ]

    @staticmethod
    def _get_collaborative_text_patch_payloads(
        request_schema: BatchFormRequestSchema, targets: list[dict[str, str]]
    ) -> list[dict[str, str]]:
        form = request_schema.form or {}
        patch_payloads: list[dict[str, str]] = []

        for target in targets:
            form_field = target["form_field"]
            if target["type"] != "text" or form_field not in form:
                continue
            value = form.get(form_field) or ""
            patch_payloads.append(
                {
                    "document_name": target["document_name"],
                    "field": target["patch_field"],
                    "value": value if isinstance(value, str) else json_dumps(value, default=json_default),
                }
            )

        return patch_payloads

    @staticmethod
    def _remove_patched_collaborative_fields(
        request_schema: BatchFormRequestSchema,
        api_schema: ApiSchemaMap,
        targets: list[dict[str, str]],
        patched_document_names: set[str],
    ) -> bool:
        if not request_schema.form:
            return False

        form = request_schema.form
        for target in targets:
            form_field = target["form_field"]
            if target["document_name"] in patched_document_names and form_field:
                form.pop(form_field, None)

        path_params = set(api_schema["path_params"])
        return any(key not in path_params for key in form)

    @staticmethod
    def _get_collaborative_rich_patch_payloads(
        request_schema: BatchFormRequestSchema, targets: list[dict[str, str]]
    ) -> list[dict[str, str]]:
        form = request_schema.form or {}
        patch_payloads: list[dict[str, str]] = []

        for target in targets:
            form_field = target["form_field"]
            if target["type"] != "rich" or form.get(form_field) is None:
                continue

            content = form[form_field]
            if isinstance(content, dict) and isinstance(content.get("content"), str):
                patch_payloads.append({"document_name": target["document_name"], "value": content["content"]})
            elif isinstance(content, str):
                patch_payloads.append({"document_name": target["document_name"], "value": content})

        return patch_payloads

    @staticmethod
    def _patch_collaborative_documents(
        headers: Headers, text_patch_payloads: list[dict[str, str]], rich_patch_payloads: list[dict[str, str]]
    ) -> dict | None:
        request_headers = CollaborativeEditMiddleware._get_socket_request_headers(headers)
        if not request_headers:
            return CollaborativeEditMiddleware._batch_response(
                {"message": "Missing authorization for editor sync patch."}, status.HTTP_401_UNAUTHORIZED
            )

        for path, patch_payloads in (
            ("/editor-sync/text/patch", text_patch_payloads),
            ("/editor-sync/rich/patch-request", rich_patch_payloads),
        ):
            for patch_payload in patch_payloads:
                patch_response = CollaborativeEditMiddleware._patch_collaborative_document(
                    path, patch_payload, request_headers
                )
                if patch_response is not None:
                    return patch_response

        return None

    @staticmethod
    def _patch_collaborative_document(path: str, patch_payload: dict[str, str], headers: dict[str, str]) -> dict | None:
        try:
            response = requests.post(
                f"{Env.SOCKET_INTERNAL_URL}{path}",
                json=patch_payload,
                headers=headers,
                timeout=10,
            )
        except requests.RequestException as error:
            return CollaborativeEditMiddleware._batch_response(
                {"message": str(error)}, status.HTTP_503_SERVICE_UNAVAILABLE
            )

        if status.HTTP_200_OK <= response.status_code < 300:
            return None

        try:
            content = response.json()
        except ValueError:
            content = {"message": response.text}
        return CollaborativeEditMiddleware._batch_response(content, response.status_code)

    @staticmethod
    def _get_socket_request_headers(headers: Headers) -> dict[str, str]:
        request_headers: dict[str, str] = {}
        api_token = headers.get(AuthSecurity.API_TOKEN_HEADER, headers.get(AuthSecurity.API_TOKEN_HEADER.lower(), None))
        if api_token:
            request_headers[AuthSecurity.API_TOKEN_HEADER] = api_token
            return request_headers

        authorization = headers.get(
            AuthSecurity.AUTHORIZATION_HEADER, headers.get(AuthSecurity.AUTHORIZATION_HEADER.lower(), None)
        )
        if authorization:
            request_headers[AuthSecurity.AUTHORIZATION_HEADER] = authorization

        cookie = headers.get("cookie")
        if cookie:
            request_headers["cookie"] = cookie

        return request_headers

    @staticmethod
    def _batch_response(content: dict, status_code: int = status.HTTP_200_OK) -> dict:
        return {"status": status_code, "body": content}

    @staticmethod
    def _match_api_path(api_path: str, request_path: str) -> dict[str, str] | None:
        api_parts = [part for part in api_path.split("/") if part]
        request_parts = [part for part in request_path.split("/") if part]
        if len(api_parts) != len(request_parts):
            return None

        path_params: dict[str, str] = {}
        for api_part, request_part in zip(api_parts, request_parts):
            if api_part.startswith("{") and api_part.endswith("}"):
                path_params[api_part[1:-1]] = request_part
                continue
            if api_part != request_part:
                return None

        return path_params

    @staticmethod
    def _parse_json_body(body: bytes) -> dict | None:
        if not body:
            return None

        try:
            form = json_loads(body)
        except Exception:
            return None

        return form if isinstance(form, dict) else None

    @staticmethod
    async def _read_body(receive: Receive) -> tuple[bytes, bool]:
        body = bytearray()
        max_body_bytes = Env.MAX_FILE_SIZE_MB * 1024 * 1024
        while True:
            message = await receive()
            if message["type"] == "http.request":
                body.extend(message.get("body", b""))
                if len(body) > max_body_bytes:
                    body.clear()
                    raise ValueError(f"Request body exceeds the {Env.MAX_FILE_SIZE_MB} MB limit")
            if message["type"] != "http.request" or not message.get("more_body", False):
                return bytes(body), message["type"] == "http.disconnect"

    @staticmethod
    def _replay_body_messages(messages: list[Message]) -> Receive:
        pending_messages = list(messages)

        async def receive() -> Message:
            if pending_messages:
                return pending_messages.pop(0)
            return {"type": "http.request", "body": b"", "more_body": False}

        return receive
