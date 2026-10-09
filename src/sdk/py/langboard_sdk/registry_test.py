"""Portable declaration validation and ambiguous mutation behavior."""

from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase, main
from unittest.mock import AsyncMock
from .client import MutationOutcomeUnknown
from .definition import validate_app_definition
from .registry import AppRegistry


DECLARATION = {
    "schema_version": 1, "key": "example-erp", "version": "1.0.0", "name": "Example ERP",
    "description": "External issues.", "capabilities": ["cards.create"], "resource_types": ["issue"],
    "workflow_requirements": {"required": ["backlog"], "optional": []},
    "panel": {"url": "https://example.invalid/panel", "name": "ERP", "icon": "📋"},
}


class RegistryTests(IsolatedAsyncioTestCase):
    async def test_declaration_does_not_create_arbitrary_stages_or_authority(self):
        self.assertEqual(validate_app_definition(DECLARATION), DECLARATION)
        transport = SimpleNamespace(request=AsyncMock())
        registry = AppRegistry(transport)
        for change in [{"schema_version": True}, {"version": "latest"}, {"granted_capabilities": ["*"]},
                       {"capabilities": ["*"]}, {"workflow_requirements": {"required": ["erp-custom"], "optional": []}},
                       {"panel": {"url": "https://secret@example.invalid", "name": "ERP", "icon": "📋"}},
                       {"panel": {"url": "javascript:alert(1)", "name": "ERP", "icon": "📋"}}]:
            with self.assertRaises(ValueError):
                await registry.approve({**DECLARATION, **change})
        transport.request.assert_not_awaited()

    async def test_registration_receipt_is_required_and_never_replayed(self):
        transport = SimpleNamespace(request=AsyncMock(return_value={"app": {}}))
        with self.assertRaises(MutationOutcomeUnknown):
            await AppRegistry(transport).approve(DECLARATION)
        transport.request.assert_awaited_once()


if __name__ == "__main__":
    main()
