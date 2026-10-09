"""Management transports validate revisions and preserve uncertain outcomes."""

from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, Mock
from . import (
    AppManager,
    DokployResource,
    GlitchTipProject,
    HttpTransport,
    MutationOutcomeUnknown,
    NativeApiError,
    WorkflowStage,
)


class ManagementTests(IsolatedAsyncioTestCase):
    async def test_external_adapter_selection_needs_no_provider_branch(self):
        class MonitorSelection:
            selection_collection = "services"

            def selection_fields(self):
                return {"service_id": "service-1", "expected_resource_revision": 3}

        transport = SimpleNamespace(request=AsyncMock(return_value={"resource": {"uid": "resource"}}))
        connections = AppManager(transport, "example-monitor").connections(
            "independent-monitor", selection_collection="services"
        )
        await connections.select("connection", "a" * 64, MonitorSelection())
        transport.request.assert_awaited_once_with(
            "POST", "/board/example-monitor/settings/apps/independent-monitor/connections/connection/services",
            json={"service_id": "service-1", "expected_resource_revision": 3, "expected_revision": "a" * 64},
        )
        transport.request.reset_mock()
        for collection in ("../services", "services?override=true"):
            with self.assertRaises(ValueError):
                AppManager(transport, "board").connections("monitor", selection_collection=collection)
        bad = SimpleNamespace(selection_collection="services", selection_fields=lambda: {"expected_revision": "b" * 64})
        with self.assertRaises(ValueError):
            await connections.select("connection", "a" * 64, bad)
        transport.request.assert_not_awaited()

    async def test_workflow_uses_builtins_and_exact_revision_without_enabling_by_default(self):
        transport = SimpleNamespace(request=AsyncMock(return_value={"binding": {"uid": "binding"}}))
        apps = AppManager(transport, "board")
        await apps.catalog()
        await apps.prepare_workflow("adapter")
        await apps.save_workflow("adapter", "binding", "a" * 64, {WorkflowStage.ACTIVE: "column"})
        transport.request.assert_awaited_with(
            "PUT",
            "/board/board/settings/apps/adapter/workflow",
            json={
                "binding_uid": "binding",
                "expected_revision": "a" * 64,
                "workflow_mapping": {"active": "column"},
                "enable_transitions": False,
            },
        )
        count = transport.request.await_count
        for stage in ("custom", "../active"):
            with self.assertRaises(ValueError):
                await apps.save_workflow("adapter", "binding", "a" * 64, {stage: "column"})
        with self.assertRaises(ValueError):
            await apps.disable("adapter", "binding", "stale")
        with self.assertRaises(ValueError):
            await apps.workflow("../adapter")
        self.assertEqual(transport.request.await_count, count)

    async def test_instance_management_uses_references_and_one_explicit_resource_page(self):
        transport = SimpleNamespace(request=AsyncMock(return_value={"items": [], "next_cursor": "next"}))
        connections = AppManager(transport, "board").connections("glitchtip", selection_collection="projects")
        await connections.list(after="page")
        transport.request.assert_awaited_with(
            "GET", "/board/board/settings/apps/glitchtip/connections", params={"after": "page"}
        )
        await connections.create("https://errors.example", "secret://ref/abc")
        await connections.discover("one", organization="org", cursor="page")
        await connections.select("one", "a" * 64, GlitchTipProject("org", "project"))
        await connections.selected("one")
        await connections.remove("one", "resource", 2)
        transport.request.assert_awaited_with(
            "POST",
            "/board/board/settings/apps/glitchtip/connections/one/projects/resource/remove",
            json={"expected_revision": 2},
        )
        await connections.disconnect("one", "a" * 64)
        count = transport.request.await_count
        with self.assertRaises(ValueError):
            await connections.create("https://errors.example", "raw-token")
        with self.assertRaises(ValueError):
            await connections.remove("one", "resource", True)
        with self.assertRaises(ValueError):
            await connections.select("one", "a" * 64, DokployResource("application", "app"))
        self.assertEqual(transport.request.await_count, count)

    async def test_http_errors_never_retry_or_print_response_payload(self):
        session = SimpleNamespace(follow_redirects=False, request=AsyncMock())
        transport = HttpTransport(session)
        session.request.return_value = SimpleNamespace(status_code=409, json=Mock(return_value={"private": "detail"}))
        with self.assertRaises(NativeApiError) as captured:
            await transport.request("PUT", "/board/fixture", json={})
        self.assertEqual(captured.exception.status_code, 409)
        self.assertNotIn("private", str(captured.exception))
        session.request.assert_awaited_once()
        session.request.reset_mock()
        session.request.side_effect = TimeoutError("disconnected")
        with self.assertRaises(MutationOutcomeUnknown):
            await transport.request("POST", "/board/fixture", json={})
        session.request.assert_awaited_once()
        with self.assertRaises(TimeoutError):
            await transport.request("GET", "/board/fixture")
        session.request.side_effect = None
        for status, body in [(503, {}), (200, None)]:
            session.request.return_value = SimpleNamespace(status_code=status, json=Mock(return_value=body))
            with self.assertRaises(MutationOutcomeUnknown):
                await transport.request("POST", "/board/fixture")
        with self.assertRaises(ValueError):
            HttpTransport(SimpleNamespace(follow_redirects=True))
