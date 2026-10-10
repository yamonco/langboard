"""Bounded description anchors preserve the existing comment contract."""

from pydantic import ValidationError
from langboard_shared.core.db import EditorContentModel
from langboard_shared.core.types import SnowflakeID
from langboard_shared.domain.models import CardComment
from langboard_shared.domain.models.CardComment import CardCommentAnchorModel


def test_anchor_is_exposed_without_changing_comment_content() -> None:
    anchor = CardCommentAnchorModel(
        exact="stable quote",
        prefix="before",
        suffix="after",
        start_block="A stable quote survives edits",
        end_block="A stable quote survives edits",
        start_path=[2],
        end_path=[2],
    )
    comment = CardComment(
        card_id=SnowflakeID(1), content=EditorContentModel(content="Review this"), anchor=anchor.model_dump()
    )
    response = comment.api_response()
    assert response["content"] == {"content": "Review this"}
    assert response["anchor"] == anchor.model_dump()


def test_anchor_rejects_unbounded_quotes() -> None:
    try:
        CardCommentAnchorModel(exact="x" * 4097)
    except ValidationError:
        pass
    else:
        raise AssertionError("oversized quote must be rejected")
