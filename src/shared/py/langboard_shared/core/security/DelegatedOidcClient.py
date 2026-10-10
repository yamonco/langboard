from json import dumps as json_dumps
from typing import Any
from uuid import UUID
import httpx
from jwt import decode as jwt_decode
from jwt import get_unverified_header
from jwt.algorithms import ECAlgorithm
from ...Env import Env
from ..caching import Cache
from ..utils.decorators import staticclass


@staticclass
class DelegatedOidcClient:
    """Validate short-lived, replay-protected end-user assertions from a trusted gateway."""

    @staticmethod
    def validate(assertion: str) -> dict[str, Any]:
        issuer = Env.OIDC_DELEGATED_ISSUER.strip().rstrip("/")
        jwks_url = Env.OIDC_DELEGATED_JWKS_URL.strip()
        audience = Env.OIDC_DELEGATED_AUDIENCE.strip()
        trusted_actors = Env.OIDC_DELEGATED_ACTOR_SUBJECTS
        max_ttl = Env.OIDC_DELEGATED_MAX_TTL_SEC
        clock_skew = Env.OIDC_DELEGATED_CLOCK_SKEW_SEC
        if not issuer or not issuer.startswith("https://") or not jwks_url.startswith("https://"):
            raise RuntimeError("Delegated OIDC issuer and JWKS URL must use HTTPS")
        if not audience or not trusted_actors or max_ttl <= 0 or max_ttl > 120 or clock_skew < 0 or clock_skew > 30:
            raise RuntimeError("Delegated OIDC trust policy is incomplete")

        header = get_unverified_header(assertion)
        if header.get("alg") != "ES256" or header.get("typ") != "JWT":
            raise RuntimeError("Delegated assertion algorithm or type is invalid")
        kid = str(header.get("kid", "")).strip()
        if not kid:
            raise RuntimeError("Delegated assertion kid is missing")

        jwk = DelegatedOidcClient._find_jwk(kid)
        if not jwk:
            raise RuntimeError("Delegated assertion signing key is not found")
        signing_key = ECAlgorithm.from_jwk(json_dumps(jwk))
        claims = jwt_decode(
            assertion,
            key=signing_key,
            algorithms=["ES256"],
            audience=audience,
            issuer=issuer,
            leeway=clock_skew,
            options={"require": ["sub", "iss", "aud", "exp", "iat", "nbf", "jti", "act"]},
        )

        if claims.get("aud") != audience:
            raise RuntimeError("Delegated assertion audience must be an exact string")
        subject = str(claims.get("sub", "")).strip()
        actor = claims.get("act")
        actor_subject = str(actor.get("sub", "")).strip() if isinstance(actor, dict) else ""
        if not subject or actor_subject not in trusted_actors:
            raise RuntimeError("Delegated assertion subject or actor is not trusted")

        issued_at = claims.get("iat")
        not_before = claims.get("nbf")
        expires_at = claims.get("exp")
        if not all(
            isinstance(value, int) and not isinstance(value, bool) for value in (issued_at, not_before, expires_at)
        ):
            raise RuntimeError("Delegated assertion timestamps must be integers")
        if expires_at <= issued_at or expires_at - issued_at > max_ttl or not_before < issued_at:
            raise RuntimeError("Delegated assertion lifetime is invalid")

        jti = str(claims.get("jti", "")).strip()
        try:
            parsed_jti = UUID(jti)
        except ValueError as exc:
            raise RuntimeError("Delegated assertion jti must be UUIDv4") from exc
        if parsed_jti.version != 4 or str(parsed_jti) != jti.lower():
            raise RuntimeError("Delegated assertion jti must be canonical UUIDv4")

        replay_ttl = max_ttl + clock_skew
        replay_key = f"oidc:delegated:replay:{issuer}:{jti}"
        if not Cache.set_if_absent(replay_key, True, replay_ttl):
            raise RuntimeError("Delegated assertion was already used")
        return claims

    @staticmethod
    def _find_jwk(kid: str) -> dict[str, Any] | None:
        jwks = DelegatedOidcClient.get_jwks()
        keys = jwks.get("keys", [])
        if not isinstance(keys, list):
            return None
        for key in keys:
            if (
                isinstance(key, dict)
                and key.get("kid") == kid
                and key.get("kty") == "EC"
                and key.get("crv") == "P-256"
                and key.get("alg", "ES256") == "ES256"
                and key.get("use", "sig") == "sig"
            ):
                return key
        return None

    @staticmethod
    def get_jwks() -> dict[str, Any]:
        cache_key = f"oidc:delegated:jwks:{Env.OIDC_DELEGATED_JWKS_URL}"
        cached = Cache.get(cache_key)
        if isinstance(cached, dict):
            return cached
        try:
            with httpx.Client(timeout=Env.OIDC_TIMEOUT_SEC) as client:
                response = client.get(Env.OIDC_DELEGATED_JWKS_URL, headers={"Accept": "application/json"})
            response.raise_for_status()
            payload = response.json()
        except Exception as exc:
            raise RuntimeError("Delegated OIDC JWKS request failed") from exc
        if not isinstance(payload, dict):
            raise RuntimeError("Delegated OIDC JWKS payload is invalid")
        Cache.set(cache_key, payload, Env.OIDC_JWKS_CACHE_TTL_SEC)
        return payload
