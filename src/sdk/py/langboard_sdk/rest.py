"""REST transport using a caller-owned authenticated async HTTP session."""

from typing import Any, Protocol
from .client import MutationOutcomeUnknown


class ApiTransport(Protocol):
    async def request(self, method: str, path: str, *, params: dict | None = None, json: dict | None = None) -> dict:
        """One native API request; ambiguous mutations must never be retried."""
        ...


class NativeApiError(RuntimeError):
    def __init__(self, status_code: int, method: str, path: str, result: Any):
        self.status_code, self.method, self.path, self.result = status_code, method, path, result
        super().__init__(f"Langboard API returned HTTP {status_code}")


class HttpTransport:
    """Accept an authenticated httpx-compatible AsyncClient; no auth or lifecycle ownership.

    Configure its base_url to the native API origin, timeout and credentials.
    It must have redirects and retries disabled. The SDK never fetches credentials.
    """

    def __init__(self, session: Any):
        if getattr(session, "follow_redirects", False):
            raise ValueError("Management sessions must not follow redirects")
        self.session = session

    async def request(self, method: str, path: str, *, params: dict | None = None, json: dict | None = None) -> dict:
        mutation = method.upper() not in {"GET", "HEAD", "OPTIONS"}
        try:
            response = await self.session.request(method, path, params=params, json=json)
        except Exception as error:
            if mutation:
                raise MutationOutcomeUnknown(
                    "API mutation response unavailable; read current state before retrying"
                ) from error
            raise
        try:
            result = response.json()
        except Exception:
            result = None
        if not 200 <= response.status_code < 300:
            if mutation and response.status_code >= 500:
                raise MutationOutcomeUnknown("API mutation returned a server error; read current state before retrying")
            raise NativeApiError(response.status_code, method, path, result)
        if not isinstance(result, dict):
            if mutation:
                raise MutationOutcomeUnknown("API mutation receipt unavailable; read current state before retrying")
            raise RuntimeError("Langboard API returned an invalid response")
        return result
