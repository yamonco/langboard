from enum import Enum
from json import dumps as json_dumps
from json import loads as json_loads
from re import escape as re_escape
from re import fullmatch as re_fullmatch
from re import sub as re_sub
from fastapi import Request, status
from langboard_shared.core.routing import AppRouter
from langboard_shared.core.routing.ApiSchemaHelper import ApiSchemaMap
from langboard_shared.core.utils.Converter import json_default
from langboard_shared.domain.models import Bot, User
from langboard_shared.Env import Env
from starlette.types import Message
from .BatchForm import BatchFormRequestSchema


async def execute_batch_request_schemas(
    request: Request,
    request_schemas: list[BatchFormRequestSchema],
    user_or_bot: User | Bot,
    allowed_permissions: set[str] | None,
) -> list[dict]:
    api_methods = {"GET", "POST", "PUT", "DELETE"}
    responses = []
    response_size_limit = Env.BATCH_MAX_RESPONSE_SIZE_MB * 1024 * 1024
    response_size = 0
    for request_schema in request_schemas:
        if request_schema.method.upper() not in api_methods:
            responses.append(create_batch_response({}, status.HTTP_400_BAD_REQUEST))
            continue

        api_schema, request_path, error_response = resolve_batch_request(request_schema, allowed_permissions)
        if error_response is not None:
            responses.append(error_response)
            continue
        if api_schema is None:
            responses.append(create_batch_response({"message": "API schema not found."}, status.HTTP_404_NOT_FOUND))
            continue

        query_string = query_dict_to_bytes(request_schema.query or {})
        scope = {
            "type": "http",
            "method": request_schema.method,
            "path": request_path,
            "query_string": query_string,
            "headers": get_internal_request_headers(request),
            "auth": user_or_bot,
            "is_batch": True,
            "batch_api_schema": api_schema,
        }

        response = {}
        response_body_parts: list[bytes] = []
        response_limit_exceeded = False
        responses.append(response)

        async def receive():
            message = b""
            if request_schema.form:
                message = json_dumps(request_schema.form, default=json_default).encode()
            return {"type": "http.request", "body": message, "more_body": False}

        async def send(message: Message):
            nonlocal response_limit_exceeded, response_size

            message_type = message.get("type")
            if message_type == "http.response.start":
                response["status"] = message.get("status", status.HTTP_200_OK)
                return

            if message_type != "http.response.body":
                return

            body = message.get("body", b"{}")
            response_size += len(body)
            if response_size > response_size_limit:
                response_body_parts.clear()
                response_limit_exceeded = True
                response["status"] = status.HTTP_413_REQUEST_ENTITY_TOO_LARGE
                response["body"] = {"message": f"Batch response exceeds the {Env.BATCH_MAX_RESPONSE_SIZE_MB} MB limit."}
                return
            if response_limit_exceeded:
                return

            response_body_parts.append(body)
            if message.get("more_body", False):
                return

            body = b"".join(response_body_parts)
            try:
                response["body"] = json_loads(body) if body else {}
            except Exception:
                response["body"] = {"error": "Invalid JSON response"}

        await AppRouter.get_app()(scope, receive, send)
        if response_limit_exceeded:
            break

    return responses


def create_batch_response(content: dict, status_code: int = status.HTTP_200_OK) -> dict:
    return {"status": status_code, "body": content}


def resolve_batch_request(
    request_schema: BatchFormRequestSchema, allowed_permissions: set[str] | None
) -> tuple[ApiSchemaMap | None, str, dict | None]:
    api_schema = get_batch_api_schema(request_schema)
    if not api_schema:
        return (
            None,
            request_schema.path_or_api_name,
            create_batch_response({"message": "API schema not found."}, status.HTTP_404_NOT_FOUND),
        )

    if api_schema["path"] == "/batch":
        return (
            None,
            request_schema.path_or_api_name,
            create_batch_response({"message": "Nested batch requests are not allowed."}, status.HTTP_400_BAD_REQUEST),
        )

    if request_schema.method.upper() != api_schema["method"].upper():
        return (
            None,
            request_schema.path_or_api_name,
            create_batch_response({"message": "API method does not match."}, status.HTTP_405_METHOD_NOT_ALLOWED),
        )

    permission = api_schema["permission"]
    permission_value = permission.value if isinstance(permission, Enum) else permission
    if allowed_permissions is not None and permission_value not in allowed_permissions:
        return (
            None,
            request_schema.path_or_api_name,
            create_batch_response(
                {"message": "Not enough permissions to access this endpoint."}, status.HTTP_403_FORBIDDEN
            ),
        )

    request_params = {**(request_schema.form or {}), **(request_schema.query or {})}
    missing_path_params = [path_param for path_param in api_schema["path_params"] if path_param not in request_params]
    if missing_path_params:
        return (
            None,
            request_schema.path_or_api_name,
            create_batch_response(
                {"message": f"Missing path parameter(s): {', '.join(missing_path_params)}"}, status.HTTP_400_BAD_REQUEST
            ),
        )

    return api_schema, get_request_path(request_schema, api_schema), None


def get_batch_api_schema(request_schema: BatchFormRequestSchema) -> ApiSchemaMap | None:
    api_schema = AppRouter.api_routes.get(request_schema.path_or_api_name)
    if api_schema:
        return api_schema

    for schema in AppRouter.api_routes.values():
        if schema["method"].upper() != request_schema.method.upper():
            continue
        if matches_api_path(schema["path"], request_schema.path_or_api_name):
            return schema

    return None


def get_request_path(request_schema: BatchFormRequestSchema, api_schema: ApiSchemaMap) -> str:
    if request_schema.path_or_api_name not in AppRouter.api_routes:
        return request_schema.path_or_api_name

    try:
        return api_schema["path"].format(**{**(request_schema.form or {}), **(request_schema.query or {})})
    except Exception:
        return api_schema["path"]


def matches_api_path(api_path: str, request_path: str) -> bool:
    pattern = re_escape(api_path)
    pattern = re_sub(r"\\\{[^}]+\\\}", r"[^/]+", pattern)
    return re_fullmatch(pattern, request_path) is not None


def query_dict_to_bytes(query: dict) -> bytes:
    return b"&".join(f"{key}={value}".encode() for key, value in query.items() if value is not None)


def get_internal_request_headers(request: Request) -> list[tuple[bytes, bytes]]:
    return [(key, value) for key, value in request.headers.raw if key.lower() != b"accept-encoding"]
