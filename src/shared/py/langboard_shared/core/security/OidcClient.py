from json import dumps as json_dumps
from typing import Any
from urllib.parse import urlencode
import httpx
from jwt import decode as jwt_decode
from jwt import get_unverified_header
from jwt.algorithms import RSAAlgorithm
from ...Env import Env
from ..caching import Cache
from ..utils.decorators import staticclass


@staticclass
class OidcClient:
    @staticmethod
    def is_enabled() -> bool:
        if not Env.OIDC_ENABLED:
            return False
        if not Env.OIDC_CLIENT_ID:
            return False
        if not Env.OIDC_ISSUER and not Env.OIDC_DISCOVERY_URL:
            return False
        return True

    @staticmethod
    def build_authorize_url(state: str, nonce: str) -> str:
        discovery = OidcClient.get_discovery()
        authorization_endpoint = str(discovery.get("authorization_endpoint", "")).strip()
        if not authorization_endpoint:
            raise RuntimeError("OIDC authorization_endpoint is missing")

        payload = {
            "client_id": Env.OIDC_CLIENT_ID,
            "response_type": "code",
            "redirect_uri": Env.OIDC_REDIRECT_URI,
            "scope": Env.OIDC_SCOPES,
            "state": state,
            "nonce": nonce,
        }
        if Env.OIDC_PROMPT:
            payload["prompt"] = Env.OIDC_PROMPT

        return f"{authorization_endpoint}?{urlencode(payload)}"

    @staticmethod
    def exchange_code(code: str) -> dict[str, Any]:
        discovery = OidcClient.get_discovery()
        token_endpoint = str(discovery.get("token_endpoint", "")).strip()
        if not token_endpoint:
            raise RuntimeError("OIDC token_endpoint is missing")

        payload = {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": Env.OIDC_REDIRECT_URI,
            "client_id": Env.OIDC_CLIENT_ID,
        }
        if Env.OIDC_CLIENT_SECRET:
            payload["client_secret"] = Env.OIDC_CLIENT_SECRET

        response_json = OidcClient._request_json("POST", token_endpoint, data=payload)
        if "id_token" not in response_json and "access_token" not in response_json:
            raise RuntimeError("OIDC token response is invalid")
        return response_json

    @staticmethod
    def validate_id_token(id_token: str, nonce: str | None = None) -> dict[str, Any]:
        return OidcClient._validate_jwt(id_token, Env.OIDC_CLIENT_ID, nonce)

    @staticmethod
    def validate_access_token(access_token: str) -> dict[str, Any]:
        """Validate an OIDC access token intended only for the Langboard resource."""

        if not Env.OIDC_BEARER_ENABLED:
            raise RuntimeError("OIDC bearer authentication is disabled")
        audience = Env.OIDC_RESOURCE_AUDIENCE.strip()
        if not audience:
            raise RuntimeError("OIDC resource audience is missing")
        return OidcClient._validate_jwt(access_token, audience)

    @staticmethod
    def _validate_jwt(token: str, audience: str, nonce: str | None = None) -> dict[str, Any]:
        """Validate one asymmetric OIDC JWT against discovery metadata."""

        discovery = OidcClient.get_discovery()
        unverified_header = get_unverified_header(token)

        algorithm = str(unverified_header.get("alg", "RS256"))
        if algorithm.lower() == "none":
            raise RuntimeError("OIDC ID token algorithm 'none' is not allowed")
        if algorithm.startswith("HS"):
            signing_key: Any = Env.OIDC_CLIENT_SECRET
            if not signing_key:
                raise RuntimeError("OIDC client secret is required for HMAC-signed ID tokens")
        else:
            jwk = OidcClient._find_jwk(unverified_header)
            if not jwk:
                raise RuntimeError("OIDC JWK for ID token is not found")
            signing_key = RSAAlgorithm.from_jwk(json_dumps(jwk))

        issuer = str(discovery.get("issuer", Env.OIDC_ISSUER)).strip()
        if not issuer:
            raise RuntimeError("OIDC issuer is missing")

        payload = jwt_decode(
            token,
            key=signing_key,
            algorithms=[algorithm],
            audience=audience,
            issuer=issuer,
            leeway=Env.OIDC_CLOCK_SKEW_SEC,
            options={"require": ["sub", "iss", "aud", "exp", "iat"]},
        )

        if nonce is not None and str(payload.get("nonce", "")) != nonce:
            raise RuntimeError("OIDC nonce mismatch")

        return payload

    @staticmethod
    def fetch_userinfo(access_token: str) -> dict[str, Any]:
        discovery = OidcClient.get_discovery()
        userinfo_endpoint = str(discovery.get("userinfo_endpoint", "")).strip()
        if not userinfo_endpoint:
            return {}
        return OidcClient._request_json(
            "GET",
            userinfo_endpoint,
            headers={"Authorization": f"Bearer {access_token}"},
        )

    @staticmethod
    def get_discovery() -> dict[str, Any]:
        cache_key = "oidc:discovery"
        cached = Cache.get(cache_key)
        if isinstance(cached, dict):
            return cached

        discovery_url = OidcClient._get_discovery_url()
        if not discovery_url:
            raise RuntimeError("OIDC discovery URL is missing")
        data = OidcClient._request_json("GET", discovery_url)
        Cache.set(cache_key, data, Env.OIDC_DISCOVERY_CACHE_SEC)
        return data

    @staticmethod
    def get_jwks() -> dict[str, Any]:
        cache_key = "oidc:jwks"
        cached = Cache.get(cache_key)
        if isinstance(cached, dict):
            return cached

        discovery = OidcClient.get_discovery()
        jwks_uri = str(discovery.get("jwks_uri", "")).strip()
        if not jwks_uri:
            raise RuntimeError("OIDC jwks_uri is missing")
        data = OidcClient._request_json("GET", jwks_uri)
        Cache.set(cache_key, data, Env.OIDC_JWKS_CACHE_TTL_SEC)
        return data

    @staticmethod
    def _get_discovery_url() -> str:
        if Env.OIDC_DISCOVERY_URL:
            return Env.OIDC_DISCOVERY_URL
        issuer = Env.OIDC_ISSUER.rstrip("/")
        if not issuer:
            return ""
        return f"{issuer}/.well-known/openid-configuration"

    @staticmethod
    def _find_jwk(unverified_header: dict[str, Any]) -> dict[str, Any] | None:
        jwks = OidcClient.get_jwks()
        keys = jwks.get("keys", [])
        if not isinstance(keys, list):
            return None

        kid = unverified_header.get("kid")
        if kid is not None:
            for key in keys:
                if isinstance(key, dict) and key.get("kid") == kid:
                    return key

        # Fallback for providers that omit kid.
        for key in keys:
            if isinstance(key, dict):
                return key
        return None

    @staticmethod
    def _request_json(
        method: str,
        url: str,
        data: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        request_headers = {"Accept": "application/json", **(headers or {})}
        try:
            with httpx.Client(timeout=Env.OIDC_TIMEOUT_SEC) as client:
                response = client.request(method=method, url=url, data=data, headers=request_headers)
            response.raise_for_status()
            payload = response.json()
            if not isinstance(payload, dict):
                raise RuntimeError("OIDC response payload is invalid")
            return payload
        except Exception as e:
            raise RuntimeError(f"OIDC request failed: {method} {url}") from e
