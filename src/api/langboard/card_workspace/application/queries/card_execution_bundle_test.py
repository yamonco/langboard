"""Keep execution readiness in the card bundle additive and exactly as persisted."""

import os
from types import SimpleNamespace


os.environ.setdefault("PROJECT_NAME", "langboard")

from ...domain import CardBundleInclude, CommentPage, SectionPage  # noqa: E402
from ..ports import CardBundleSource, CardExecutionSource  # noqa: E402
from . import get_card_bundle  # noqa: E402


def _source() -> CardBundleSource:
    return CardBundleSource(
        details={"uid": "card", "title": "Test"},
        checklists=[],
        attachments=[],
        metadata={},
        bot_scopes=[],
        bot_schedules=[],
    )


def _port(readiness: CardExecutionSource) -> SimpleNamespace:
    return SimpleNamespace(
        get_card_bundle_source=lambda *_: _source(),
        get_card_execution=lambda *_: readiness,
    )


def test_bundle_carries_execution_readiness_exactly_as_persisted() -> None:
    """A ready card proves it with its generation; a non-ready card stays fail-closed."""

    for readiness in (
        CardExecutionSource(is_ready=True, generation=4),
        CardExecutionSource(is_ready=False, generation=1),
    ):
        result = get_card_bundle(
            _port(readiness),
            "project",
            "card",
            CommentPage(),
            SectionPage(),
            [CardBundleInclude.Execution],
        )

        assert result.model_dump()["card"]["execution"] == {
            "is_ready": readiness.is_ready,
            "generation": readiness.generation,
        }


def test_bundle_omits_execution_when_the_section_is_not_requested() -> None:
    """Callers that do not opt in keep receiving the previous payload shape."""

    result = get_card_bundle(
        _port(CardExecutionSource(is_ready=True, generation=4)),
        "project",
        "card",
        CommentPage(),
        SectionPage(),
    )

    assert "execution" not in result.model_dump()["card"]
