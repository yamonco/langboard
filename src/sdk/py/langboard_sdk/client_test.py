"""Protocol checks run with only the SDK and Python standard library."""

from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase, main
from unittest.mock import AsyncMock
from .client import LangboardClient, MutationOutcomeUnknown
from .mcp import McpTransport


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


if __name__ == "__main__":
    main()
