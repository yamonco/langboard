"""Instance administrator registration for separately hosted apps."""

import re
from .client import MutationOutcomeUnknown
from .definition import validate_app_definition
from .rest import ApiTransport


class AppRegistry:
    def __init__(self, transport: ApiTransport):
        self._transport = transport

    async def list(self) -> list[dict]:
        result = await self._transport.request("GET", "/settings/apps/registry")
        if not isinstance(result.get("apps"), list):
            raise RuntimeError("App registry snapshot unavailable")
        return result["apps"]

    async def approve(self, declaration: dict, *, expected_revision: str | None = None) -> dict:
        declaration = validate_app_definition(declaration)
        if expected_revision is not None:
            self._revision(expected_revision)
        result = await self._transport.request("POST", "/settings/apps/registry", json={
            "declaration": declaration, "expected_revision": expected_revision,
        })
        return self._receipt(result, declaration["key"])

    async def disable(self, app_key: str, expected_revision: str) -> dict:
        if not re.fullmatch(r"[a-z][a-z0-9_-]{0,31}", app_key):
            raise ValueError("Invalid app key")
        self._revision(expected_revision)
        result = await self._transport.request("POST", f"/settings/apps/registry/{app_key}/disable", json={
            "expected_revision": expected_revision,
        })
        return self._receipt(result, app_key)

    @staticmethod
    def _revision(value):
        if not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{64}", value):
            raise ValueError("A reviewed app revision is required")

    @staticmethod
    def _receipt(result, key):
        app = result.get("app")
        if (not isinstance(app, dict) or not isinstance(app.get("declaration"), dict)
                or app["declaration"].get("key") != key or type(app.get("is_enabled")) is not bool
                or type(app.get("generation")) is not int or app["generation"] < 1
                or not isinstance(app.get("revision"), str) or not re.fullmatch(r"[0-9a-f]{64}", app["revision"])):
            raise MutationOutcomeUnknown("App registration receipt unavailable; read registry before retrying")
        return app
