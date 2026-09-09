from calendar import timegm
from datetime import timedelta
from json import dumps as json_dumps
from json import loads as json_loads
from typing import Any, Literal
from fastapi import FastAPI
from fastapi.openapi.utils import get_openapi
from jwt import ExpiredSignatureError, InvalidTokenError
from jwt import decode as jwt_decode
from jwt import encode as jwt_encode
from starlette.datastructures import Headers
from ...Env import Env
from ..filter import AuthFilter
from ..routing.AppExceptionHandlingRoute import AppExceptionHandlingRoute
from ..types import SafeDateTime, SnowflakeID
from ..utils.decorators import staticclass
from ..utils.Encryptor import Encryptor


@staticclass
class AuthSecurity:
    AUTHORIZATION_HEADER = "Authorization"
    REAL_IP_HEADER = "X-Real-IP"
    FORWARDED_FOR_HEADER = "X-Forwarded-For"
    API_TOKEN_HEADER = "X-Api-Token"
    API_KEY_HEADER = "X-Api-Key"
    MCP_TOOL_GROUP_UID_HEADER = "X-MCP-Tool-Group-UID"
    MCP_USER_ASSERTION_HEADER = "X-MCP-User-Assertion"

    @staticmethod
    def authenticate(user_id: SnowflakeID) -> tuple[str, str]:
        """Authenticates the user and returns the access and refresh tokens.

        :param user_id: The user ID.
        """
        access_token = AuthSecurity.create_access_token(user_id)
        refresh_token = AuthSecurity.create_refresh_token(user_id)

        return access_token, refresh_token

    @staticmethod
    def refresh(token: str) -> str:
        """Refreshes the access token using the refresh token.

        :param token: The refresh token.

        :raises InvalidTokenError: If the token is invalid.
        :raises ExpiredSignatureError: If the signature has expired.
        """
        try:
            payload = AuthSecurity.decode_refresh_token(token)
        except ExpiredSignatureError as e:
            raise e
        except Exception:
            raise InvalidTokenError("Invalid token")

        access_token = AuthSecurity.create_access_token(payload["sub"])
        return access_token

    @staticmethod
    def set_openapi_schema(app: FastAPI):
        if app.openapi_schema:
            openapi_schema = app.openapi_schema
        else:
            openapi_schema = get_openapi(
                title=Env.PROJECT_NAME.capitalize(),
                version=Env.PROJECT_VERSION,
                routes=app.routes,
            )

        if "components" not in openapi_schema:
            openapi_schema["components"] = {}

        if "securitySchemes" not in openapi_schema["components"]:
            openapi_schema["components"]["securitySchemes"] = {}

        auth_schema = {
            "type": "http",
            "scheme": "bearer",
        }

        openapi_schema["components"]["securitySchemes"]["BearerAuth"] = auth_schema

        for route in app.routes:
            if not isinstance(route, AppExceptionHandlingRoute):
                continue
            if AuthFilter.exists(route.endpoint):
                if route.path.count(":") > 0:
                    route_path = route.path.split("/")
                    for i, part in enumerate(route_path):
                        if part.count(":") > 0:
                            route_path[i] = part.split(":", maxsplit=1)[0] + "}"
                    route_path = "/".join(route_path)
                else:
                    route_path = route.path
                path = openapi_schema["paths"][route_path]
                for method in route.methods:
                    path_method = path[method.lower()]
                    path_method["security"] = [{"BearerAuth": []}]

        app.openapi_schema = openapi_schema

    @staticmethod
    def get_client_ip(headers: Headers | dict[str, str]) -> str | None:
        real_ip = headers.get(AuthSecurity.REAL_IP_HEADER, headers.get(AuthSecurity.REAL_IP_HEADER.lower()))
        if real_ip:
            return real_ip.strip()
        forwarded_for = headers.get(
            AuthSecurity.FORWARDED_FOR_HEADER, headers.get(AuthSecurity.FORWARDED_FOR_HEADER.lower())
        )
        if forwarded_for:
            ips = [ip.strip() for ip in forwarded_for.split(",")]
            if ips:
                return ips[-1]
        return None

    @staticmethod
    def get_all_client_ips(headers: Headers | dict[str, str]) -> list[str]:
        ips: list[str] = []
        real_ip = headers.get(AuthSecurity.REAL_IP_HEADER, headers.get(AuthSecurity.REAL_IP_HEADER.lower()))
        if real_ip:
            ips.append(real_ip.strip())
        forwarded_for = headers.get(
            AuthSecurity.FORWARDED_FOR_HEADER, headers.get(AuthSecurity.FORWARDED_FOR_HEADER.lower())
        )
        if forwarded_for:
            ips.extend([ip.strip() for ip in forwarded_for.split(",")])
        ips = ",".join(ips).split(",")
        ips = [ip.strip() for ip in ips if ip.strip()]
        return ips

    @staticmethod
    def create_access_token(user_id: int) -> str:
        payload = AuthSecurity.__create_payload(user_id, timedelta(seconds=Env.JWT_AT_EXPIRATION))
        return jwt_encode(payload=payload, key=Env.JWT_SECRET_KEY, algorithm=Env.JWT_ALGORITHM)

    @staticmethod
    def create_refresh_token(user_id: int) -> str:
        payload = AuthSecurity.__create_payload(user_id, timedelta(days=Env.JWT_RT_EXPIRATION))
        return Encryptor.encrypt(json_dumps(payload), Env.JWT_SECRET_KEY)

    @staticmethod
    def compare_tokens(access_token: str | None, refresh_token: str | None) -> bool | Literal["expired_access"]:
        if not access_token or not refresh_token:
            return False

        try:
            access_payload = AuthSecurity.decode_access_token(access_token)
        except ExpiredSignatureError:
            return "expired_access"
        except Exception:
            return False

        try:
            refresh_payload = AuthSecurity.decode_refresh_token(refresh_token)
        except Exception:
            return False

        return access_payload["sub"] == refresh_payload["sub"] and access_payload["iss"] == refresh_payload["iss"]

    @staticmethod
    def decode_access_token(token: str) -> dict[str, Any]:
        payload = jwt_decode(jwt=token, key=Env.JWT_SECRET_KEY, algorithms=[Env.JWT_ALGORITHM], issuer=Env.PROJECT_NAME)
        AuthSecurity.__validate_payload(payload)
        return payload

    @staticmethod
    def decode_refresh_token(token: str) -> dict[str, Any]:
        payload = json_loads(Encryptor.decrypt(token, Env.JWT_SECRET_KEY))
        AuthSecurity.__validate_payload(payload)
        return payload

    @staticmethod
    def __create_payload(user_id: int, expiration: timedelta) -> dict[str, Any]:
        expiry = SafeDateTime.now() + expiration
        return {"sub": str(user_id), "exp": timegm(expiry.utctimetuple()), "iss": Env.PROJECT_NAME}

    @staticmethod
    def __validate_payload(payload: dict[str, Any]):
        if not isinstance(payload, dict):
            raise InvalidTokenError("Invalid token")
        if "sub" not in payload or "iss" not in payload or "exp" not in payload:
            raise InvalidTokenError("Invalid token structure")
        if (
            payload["iss"] != Env.PROJECT_NAME
            or not isinstance(payload["sub"], str)
            or not isinstance(payload["exp"], int)
        ):
            raise InvalidTokenError("Invalid token structure")
        if payload["exp"] <= timegm(SafeDateTime.now().utctimetuple()):
            raise ExpiredSignatureError("Signature has expired")
