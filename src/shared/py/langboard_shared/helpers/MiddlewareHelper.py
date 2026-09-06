from typing import TYPE_CHECKING
from fastapi import status
from starlette.datastructures import Headers
from starlette.types import ASGIApp, Message, Receive, Scope, Send
from ..core.security import AuthSecurity
from ..core.utils.decorators import staticclass
from ..domain.models import Bot, User
from ..security import Auth


if TYPE_CHECKING:
    from ..domain.services import DomainService


@staticclass
class MiddlewareHelper:
    @staticmethod
    async def log_api_key_usage(
        app: ASGIApp, scope: Scope, receive: Receive, send: Send, domain_service: "DomainService"
    ) -> None:
        if scope["type"] != "http":
            await app(scope, receive, send)
            return

        headers = Headers(scope=scope)

        if not MiddlewareHelper._is_api_key_used(headers):
            await app(scope, receive, send)
            return

        status_holder = {"status": None}

        # Wrap send to capture status code
        async def send_wrapper(message: Message):
            status_code = message.get("status")
            status_holder["status"] = status_code
            await send(message)

        await app(scope, receive, send_wrapper)

        # Log API key usage after request completes
        api_key = scope.get("api_key")
        if status_holder["status"] is None or not api_key:
            return

        try:
            ip_address = AuthSecurity.get_client_ip(headers)

            status_code = status_holder["status"]
            is_success = status.HTTP_200_OK <= status_code < status.HTTP_400_BAD_REQUEST

            domain_service.api_key.log_usage(
                api_key=api_key,
                endpoint=scope["path"],
                method=scope["method"],
                ip_address=ip_address,
                status_code=status_code,
                is_success=is_success,
            )
        except Exception:
            pass

    @staticmethod
    def validate_auth(scope: Scope) -> User | Bot | int:
        headers = Headers(scope=scope)
        if headers.get(AuthSecurity.API_TOKEN_HEADER, headers.get(AuthSecurity.API_TOKEN_HEADER.lower())):
            validation_result = Auth.validate_user_by_api_token(headers)
            if isinstance(validation_result, User):
                scope["auth"] = validation_result
                return validation_result

            validation_result = Auth.validate_bot(headers)
            if isinstance(validation_result, Bot):
                scope["auth"] = validation_result
                return validation_result
            return validation_result

        if headers.get(AuthSecurity.API_KEY_HEADER, headers.get(AuthSecurity.API_KEY_HEADER.lower())):
            validation_result = Auth.validate_user_by_api_key(headers)
            if isinstance(validation_result, tuple):
                user, api_key = validation_result
                scope["auth"] = user
                scope["api_key"] = api_key
                return user

        validation_result = Auth.validate(headers)
        if isinstance(validation_result, User):
            scope["auth"] = validation_result
            return validation_result

        oidc_user = MiddlewareHelper._validate_oidc_user(headers)
        if oidc_user:
            scope["auth"] = oidc_user
            return oidc_user

        return validation_result

    @staticmethod
    def _validate_oidc_user(headers: Headers) -> User | None:
        """Resolve a resource-scoped OIDC token through an explicit identity link."""

        from ..core.security import OidcClient
        from ..domain.models import IdentityProvider
        from ..domain.services import DomainService
        from ..Env import Env

        if not Env.OIDC_BEARER_ENABLED:
            return None
        authorization = headers.get(AuthSecurity.AUTHORIZATION_HEADER, "")
        scheme, separator, token = authorization.partition(" ")
        token = token.strip()
        if not separator or scheme.lower() != "bearer" or not token:
            return None
        try:
            claims = OidcClient.validate_access_token(token)
            subject = str(claims.get("sub", "")).strip()
            issuer = str(claims.get("iss", "")).strip().rstrip("/")
            if not subject or not issuer:
                return None
            service = DomainService()
            try:
                user = service.identity_link.get_user_by_provider_external_id(
                    IdentityProvider.Oidc,
                    subject,
                    issuer,
                )
                if not user or not user.activated_at or user.deleted_at:
                    return None
                return user
            finally:
                service.close()
        except Exception:
            return None

    @staticmethod
    def _is_api_key_used(headers: Headers) -> bool:
        return bool(headers.get(AuthSecurity.API_KEY_HEADER, headers.get(AuthSecurity.API_KEY_HEADER.lower())))
