"""Protocol checks run with only the SDK and Python standard library."""

from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase, main
from unittest.mock import AsyncMock
from .client import LangboardClient, MutationOutcomeUnknown
from .mcp import McpTransport, NativeCommandError


class ClientTests(IsolatedAsyncioTestCase):
    async def test_review_receipt_and_same_request_replay(self):
        transport = SimpleNamespace(call=AsyncMock())
        board = LangboardClient(transport)
        plan = {"project_uid": "board", "anchor_card_uid": "card", "new_checklists": [{"title": "Work"}]}
        transport.call.return_value = {"revision": "a" * 64}
        self.assertEqual((await board.preview_work_plan(plan))["revision"], "a" * 64)
        transport.call.assert_awaited_once_with("preview_card_work_plan", {"project_uid": "board", "plan": plan})
        transport.call.reset_mock()
        receipt = {"all_succeeded": True, "applied_revision": "a" * 64, "replayed": False}
        transport.call.return_value = receipt
        self.assertEqual(await board.apply_work_plan(plan, "a" * 64, "stable"), receipt)
        first = transport.call.await_args
        transport.call.return_value = {**receipt, "replayed": True}
        await board.apply_work_plan(plan, "a" * 64, "stable")
        self.assertEqual(transport.call.await_args, first)
        transport.call.reset_mock()
        with self.assertRaises(ValueError):
            await board.apply_work_plan(plan, "invalid", "stable")
        transport.call.assert_not_awaited()
        transport.call.return_value = {**receipt, "applied_revision": "b" * 64}
        with self.assertRaises(MutationOutcomeUnknown):
            await board.apply_work_plan(plan, "a" * 64, "stable")
        self.assertEqual(transport.call.await_count, 1)

    async def test_transport_disconnect_never_retries_write(self):
        session = SimpleNamespace(call_tool=AsyncMock(side_effect=TimeoutError()))
        transport = McpTransport(session)
        with self.assertRaises(MutationOutcomeUnknown):
            await transport.call("apply_card_work_plan", {}, mutation=True)
        session.call_tool.assert_awaited_once()
        with self.assertRaises(TimeoutError):
            await transport.call("preview_card_work_plan", {})
        session.call_tool.side_effect = None
        session.call_tool.return_value = SimpleNamespace(is_error=False, structured_content={"revision": "a" * 64})
        self.assertEqual(await transport.call("preview_card_work_plan", {}), {"revision": "a" * 64})
        session.call_tool.return_value = SimpleNamespace(is_error=False, structured_content=None)
        with self.assertRaises(MutationOutcomeUnknown):
            await transport.call("apply_card_work_plan", {}, mutation=True)

    async def test_server_error_receipt_preserves_original_payload_and_never_retries(self):
        result = SimpleNamespace(
            is_error=True, structured_content={"code": "revision_conflict"}, content=["Original server error"]
        )
        session = SimpleNamespace(call_tool=AsyncMock(return_value=result))
        with self.assertRaises(NativeCommandError) as captured:
            await McpTransport(session).call("apply_card_work_plan", {"request_id": "stable"}, mutation=True)
        self.assertIs(captured.exception.result, result)
        self.assertEqual(captured.exception.command, "apply_card_work_plan")
        session.call_tool.assert_awaited_once_with(
            "apply_card_work_plan", {"request_id": "stable"}, raise_on_error=False
        )
        self.assertNotIn("revision_conflict", str(captured.exception))

    async def test_other_client_failures_preserve_cause_without_replaying_mutation(self):
        failure = RuntimeError("Protocol disconnected")
        session = SimpleNamespace(call_tool=AsyncMock(side_effect=failure))
        with self.assertRaises(MutationOutcomeUnknown) as captured:
            await McpTransport(session).call("apply_card_work_plan", {}, mutation=True)
        self.assertIs(captured.exception.__cause__, failure)
        session.call_tool.assert_awaited_once()
        with self.assertRaises(RuntimeError) as read_error:
            await McpTransport(session).call("get_card_bundle", {})
        self.assertIs(read_error.exception, failure)

    async def test_missing_receipt_is_unknown_without_retries(self):
        session = SimpleNamespace(call_tool=AsyncMock(return_value=object()))
        with self.assertRaises(MutationOutcomeUnknown):
            await McpTransport(session).call("apply_card_work_plan", {}, mutation=True)
        session.call_tool.assert_awaited_once()

    async def test_app_presentation_uses_native_metadata_and_checks_receipt(self):
        import json

        item = {
            "version": 1,
            "key": "app.glitchtip.issue",
            "axis": "origin",
            "name": "GlitchTip issue",
            "description": "App origin.",
        }
        value = json.dumps(item, ensure_ascii=False, separators=(",", ":"))
        transport = SimpleNamespace(
            call=AsyncMock(
                return_value={
                    "key": "card.presentation.v1",
                    "value": value,
                    "total_chars": len(value),
                    "truncated": False,
                }
            )
        )
        await LangboardClient(transport).set_card_presentation("p", "c", item)
        transport.call.assert_awaited_once_with(
            "save_public_card_metadata",
            {"project_uid": "p", "card_uid": "c", "key": "card.presentation.v1", "value": value},
            mutation=True,
        )
        transport.call.reset_mock()
        transport.call.return_value = {"message": "unknown"}
        with self.assertRaises(MutationOutcomeUnknown):
            await LangboardClient(transport).set_card_presentation("p", "c", item)
        transport.call.assert_awaited_once()


if __name__ == "__main__":
    main()
