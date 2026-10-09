"""Provider adapters preserve exact native revisions, scopes and routes."""

from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock
from . import DokployManager, GlitchTipManager


class ProviderTests(IsolatedAsyncioTestCase):
    async def test_read_consent_and_bounded_signal_refresh(self):
        transport = SimpleNamespace(request=AsyncMock(return_value={"accepted_count": 1}))
        glitchtip = GlitchTipManager(transport, "board")
        await glitchtip.enable_read("conn", "a" * 64, "b" * 64)
        transport.request.assert_awaited_with(
            "POST",
            "/board/board/settings/apps/glitchtip/connections/conn/read-access",
            json={"expected_connection_revision": "a" * 64, "expected_binding_revision": "b" * 64},
        )
        await glitchtip.refresh_issues("conn", "resource", "a" * 64, 2, cursor="next")
        transport.request.assert_awaited_with(
            "POST",
            "/board/board/settings/apps/glitchtip/connections/conn/projects/resource/issues/refresh",
            json={"expected_connection_revision": "a" * 64, "expected_access_revision": 2, "cursor": "next"},
        )
        dokploy = DokployManager(transport, "board")
        await dokploy.enable_read("conn", "a" * 64, "b" * 64)
        transport.request.assert_awaited_with(
            "POST",
            "/board/board/settings/apps/dokploy/connections/conn/enable-read",
            json={"expected_revision": "a" * 64, "expected_binding_revision": "b" * 64},
        )
        await dokploy.refresh_deployments("conn", "resource", "a" * 64, 2)
        transport.request.assert_awaited_with(
            "POST",
            "/board/board/settings/apps/dokploy/connections/conn/selected/resource/refresh",
            json={"expected_revision": "a" * 64, "expected_access_revision": 2},
        )
        count = transport.request.await_count
        with self.assertRaises(ValueError):
            await glitchtip.refresh_issues("conn", "resource", "a" * 64, True)
        with self.assertRaises(ValueError):
            await dokploy.enable_read("conn", "stale", "b" * 64)
        self.assertEqual(transport.request.await_count, count)

    async def test_webhook_configuration_requires_secretref_and_current_three_revisions(self):
        transport = SimpleNamespace(request=AsyncMock(return_value={"state": "pending"}))
        manager = DokployManager(transport, "board")
        await manager.configure_webhook("conn", "a" * 64, "b" * 64, 0, "secret://ref/abc", notification_id="n")
        transport.request.assert_awaited_with(
            "POST",
            "/board/board/settings/apps/dokploy/connections/conn/webhook-config",
            json={
                "expected_revision": "a" * 64,
                "expected_binding_revision": "b" * 64,
                "expected_config_revision": 0,
                "credential_reference": "secret://ref/abc",
                "notification_id": "n",
            },
        )
        await manager.verify_webhook("conn", "a" * 64, "b" * 64, 1, "https://board.example/callback")
        await manager.disable_webhook("conn", "a" * 64, "b" * 64, 1)
        await manager.webhook_health("conn")
        await manager.request_webhook_secret_input()
        count = transport.request.await_count
        with self.assertRaises(ValueError):
            await manager.configure_webhook("conn", "a" * 64, "b" * 64, 0, "raw-key")
        with self.assertRaises(ValueError):
            await manager.verify_webhook("conn", "a" * 64, "b" * 64, 0, "https://board.example/callback")
        self.assertEqual(transport.request.await_count, count)
