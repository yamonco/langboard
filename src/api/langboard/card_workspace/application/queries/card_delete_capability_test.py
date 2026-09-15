"""Keep native deletion decisions visible without exposing authority internals."""

from types import SimpleNamespace
import pytest
from ...domain import CommentPage, SectionPage
from ..ports import CardBundleSource
from . import get_card_bundle


@pytest.mark.parametrize("allowed", [True, False])
def test_card_core_preserves_native_deletion_capability(allowed: bool) -> None:
    source = CardBundleSource(
        details={
            "uid": "card",
            "title": "Test",
            "can_delete": allowed,
            "created_by_user_id": 123,
            "private_policy": "must not leak",
        },
        checklists=[],
        attachments=[],
        metadata={},
        bot_scopes=[],
        bot_schedules=[],
    )
    port = SimpleNamespace(get_card_bundle_source=lambda *_: source)
    result = get_card_bundle(port, "project", "card", CommentPage(), SectionPage())
    core = result.model_dump()["card"]["core"]
    assert core["can_delete"] is allowed
    assert "created_by_user_id" not in core and "private_policy" not in core
