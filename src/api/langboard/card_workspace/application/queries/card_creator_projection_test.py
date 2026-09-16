"""Keep card authors useful for workflow while protecting private identity fields."""

import os
from types import SimpleNamespace


os.environ.setdefault("PROJECT_NAME", "langboard")

from ...domain import CommentPage, SectionPage  # noqa: E402
from ..ports import CardBundleSource  # noqa: E402
from . import get_card_bundle  # noqa: E402


def test_card_core_exposes_only_the_public_creator_identity() -> None:
    source = CardBundleSource(
        details={
            "uid": "card",
            "title": "Test",
            "creator": {
                "uid": "author",
                "type": "user",
                "firstname": "Ada",
                "lastname": "Lovelace",
                "username": "ada",
                "email": "private@example.invalid",
                "is_admin": True,
            },
        },
        checklists=[],
        attachments=[],
        metadata={},
        bot_scopes=[],
        bot_schedules=[],
    )

    result = get_card_bundle(
        SimpleNamespace(get_card_bundle_source=lambda *_: source),
        "project",
        "card",
        CommentPage(),
        SectionPage(),
    )

    assert result.model_dump()["card"]["core"]["creator"] == {
        "uid": "author",
        "type": "user",
        "firstname": "Ada",
        "lastname": "Lovelace",
        "username": "ada",
    }
