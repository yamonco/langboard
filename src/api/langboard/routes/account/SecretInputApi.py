"""Browser-only secret material transport with origin and one-use CSRF proof."""

from json import loads
from fastapi import Request
from langboard_shared.core.filter import AuthFilter
from langboard_shared.core.routing import ApiException, AppRouter, JsonResponse
from langboard_shared.core.schema import OpenApiSchema
from langboard_shared.domain.models import User
from langboard_shared.domain.services import DomainService
from langboard_shared.domain.services.factory.SecretReferenceService import SecretReferenceUnavailable
from langboard_shared.Env import Env
from langboard_shared.security import Auth
from pydantic import SecretStr
from starlette.concurrency import run_in_threadpool
from ...secrets.SecretInput import COOKIE, TTL, complete_input, open_input


def _response(payload):
    response = JsonResponse(content=payload)
    response.headers["Cache-Control"] = "no-store"
    response.headers["Referrer-Policy"] = "no-referrer"
    return response


@AppRouter.api.get("/secret-input/{input_uid}", tags=["Account"], responses=OpenApiSchema().auth().get())
@AuthFilter.add("user")
def open_secret_input(
    input_uid: str,
    user: User = Auth.scope("user"),
    service: DomainService = DomainService.scope(),
) -> JsonResponse:
    try:
        payload, challenge = open_input(service, user, input_uid)
    except (SecretReferenceUnavailable, ValueError):
        raise ApiException.NotFound_404() from None
    response = _response(payload)
    response.set_cookie(
        COOKIE,
        challenge,
        max_age=TTL,
        httponly=True,
        secure=Env.ENVIRONMENT != "development",
        samesite="strict",
        path="/secret-input/" + input_uid,
    )
    return response


@AppRouter.api.post("/secret-input/{input_uid}", tags=["Account"], responses=OpenApiSchema().auth().get())
@AuthFilter.add("user")
async def submit_secret_input(
    input_uid: str,
    request: Request,
    user: User = Auth.scope("user"),
    service: DomainService = DomainService.scope(),
) -> JsonResponse:
    # Token-authenticated POST plus exact UI origin and an HttpOnly browser proof.
    if request.headers.get("origin") != Env.PUBLIC_UI_URL.rstrip("/"):
        raise ApiException.BadRequest_400()
    try:
        # Parse here so validation errors cannot echo submitted secret material.
        if request.headers.get("content-type", "").split(";", 1)[0] != "application/json":
            raise ValueError()
        body = bytearray()
        async for chunk in request.stream():
            if len(body) + len(chunk) > 512 * 1024:
                raise ValueError()
            body.extend(chunk)
        form = loads(body)
        if (
            not isinstance(form, dict)
            or set(form) not in ({"value"}, {"value", "reason_code"})
            or not isinstance(form["value"], str)
        ):
            raise ValueError()
        payload = await run_in_threadpool(
            complete_input,
            service,
            user,
            input_uid,
            SecretStr(form["value"]),
            request.cookies.get(COOKIE),
            form.get("reason_code", "user_input"),
        )
    except (SecretReferenceUnavailable, ValueError):
        raise ApiException.BadRequest_400() from None
    response = _response(payload)
    response.delete_cookie(COOKIE, path="/secret-input/" + input_uid)
    return response


@AppRouter.api.delete("/secret-input/{input_uid}", tags=["Account"], responses=OpenApiSchema().auth().get())
@AuthFilter.add("user")
def cancel_secret_input(
    input_uid: str,
    request: Request,
    user: User = Auth.scope("user"),
    service: DomainService = DomainService.scope(),
) -> JsonResponse:
    from ...secrets.SecretInput import cancel_input

    if request.headers.get("origin") != Env.PUBLIC_UI_URL.rstrip("/"):
        raise ApiException.BadRequest_400()
    try:
        payload = cancel_input(service, user, input_uid)
    except (SecretReferenceUnavailable, ValueError):
        raise ApiException.BadRequest_400() from None
    response = _response(payload)
    response.delete_cookie(COOKIE, path="/secret-input/" + input_uid)
    return response
