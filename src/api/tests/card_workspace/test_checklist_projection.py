from typing import Any
import pytest
from langboard.card_workspace.application.commands import reconcile_card_checklist_projection
from langboard.card_workspace.domain import ChecklistProjectionItem


class FakeCommandPort:
    """Record one bounded checklist projection reconciliation."""

    def __init__(self) -> None:
        self.calls: list[tuple[Any, ...]] = []

    def reconcile_card_checklist_projection(
        self,
        project_uid: str,
        card_uid: str,
        projection_key: str,
        title: str,
        items: list[ChecklistProjectionItem],
        expected_receipt: str | None,
    ) -> dict[str, Any]:
        self.calls.append((project_uid, card_uid, projection_key, title, items, expected_receipt))
        return {
            "changed": True,
            "receipt": "a" * 64,
            "checklist": {
                "uid": "checklist1",
                "title": title,
                "is_checked": False,
                "order": 0,
                "checkitems": [
                    {
                        "uid": "item1",
                        "title": items[0].title,
                        "is_checked": items[0].is_checked,
                        "order": 0,
                        "deadline_at": items[0].deadline_at,
                    }
                ],
            },
        }


def test_reconcile_card_checklist_projection_preserves_stable_caller_keys() -> None:
    """Expose one convergent command instead of many fragile client mutations."""

    port = FakeCommandPort()
    item = ChecklistProjectionItem(
        "invoice-1",
        "Invoice collected",
        True,
        "2026-09-10T23:59:59+09:00",
    )

    result = reconcile_card_checklist_projection(
        port,
        "project1",
        "card1",
        "billing.acme",
        "Collection status",
        [item],
    )

    assert result["changed"] is True
    assert result["receipt"] == "a" * 64
    assert result["checklist"]["checkitems"][0]["title"] == "Invoice collected"
    assert port.calls[0][2:5] == ("billing.acme", "Collection status", [item])


def test_reconcile_card_checklist_projection_rejects_duplicate_item_keys() -> None:
    """Reject ambiguous ownership before the adapter mutates a card."""

    port = FakeCommandPort()
    duplicate = ChecklistProjectionItem("same", "First")

    with pytest.raises(ValueError, match="duplicates"):
        reconcile_card_checklist_projection(
            port,
            "project1",
            "card1",
            "billing.acme",
            "Collection status",
            [duplicate, ChecklistProjectionItem("same", "Second")],
        )

    assert port.calls == []
