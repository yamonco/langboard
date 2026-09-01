from fastapi import status
from langboard_shared.core.filter import AuthFilter, FilterMiddleware
from langboard_shared.core.routing import ApiErrorCode, JsonResponse
from langboard_shared.domain.models import Bot, User
from langboard_shared.domain.services import DomainService
from langboard_shared.Env import Env
from langboard_shared.helpers import MiddlewareHelper
from starlette.middleware.authentication import AuthenticationMiddleware
from starlette.routing import BaseRoute
from starlette.types import ASGIApp


class ApiAuthMiddleware(AuthenticationMiddleware, FilterMiddleware):
    """Checks if the user is authenticated and has the correct permissions."""

    __auto_load__ = False

    def __init__(self, app: ASGIApp, routes: list[BaseRoute]):
        FilterMiddleware.__init__(self, app, routes, AuthFilter)

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] != "http" or scope.get("is_batch", False):
            await self.app(scope, receive, send)
            return

        should_filter, child_scope = self.should_filter(scope)
        is_secure = Env.PUBLIC_UI_URL.startswith("https://")

        if should_filter:
            validation_result = MiddlewareHelper.validate_auth(scope)
            if isinstance(validation_result, int):
                response = JsonResponse(status_code=validation_result)
                if validation_result != status.HTTP_422_UNPROCESSABLE_CONTENT:
                    response.delete_cookie(
                        Env.REFRESH_TOKEN_NAME,
                        domain=Env.DOMAIN if Env.DOMAIN else None,
                        httponly=True,
                        secure=is_secure,
                    )
                await response(scope, receive, send)
                return

            accessible_type = AuthFilter.get_filtered(child_scope["endpoint"])
            if (
                (accessible_type == "bot" and not isinstance(validation_result, Bot))
                or (accessible_type == "user" and not isinstance(validation_result, User))
                or (
                    accessible_type == "admin"
                    and (not isinstance(validation_result, User) or not validation_result.is_admin)
                )
            ):
                response = JsonResponse(content=ApiErrorCode.AU1001, status_code=status.HTTP_403_FORBIDDEN)
                response.delete_cookie(
                    Env.REFRESH_TOKEN_NAME, domain=Env.DOMAIN if Env.DOMAIN else None, httponly=True, secure=is_secure
                )
                await response(scope, receive, send)
                return

        service = DomainService()
        try:
            await MiddlewareHelper.log_api_key_usage(self.app, scope, receive, send, service)
        finally:
            service.close()
