"""Contract and migration coverage for description-anchored comments."""

import importlib.util
from pathlib import Path
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations
from langboard_shared.core.db import EditorContentModel
from langboard_shared.core.types import SnowflakeID
from langboard_shared.domain.models import CardComment
from langboard_shared.domain.models.CardComment import CardCommentAnchorModel
from pydantic import ValidationError


ROOT = Path(__file__).resolve().parents[4]
MIGRATION = ROOT / "src/api/langboard/migrations/versions/20260911160000-c7b0d5a6e491.py"


def _anchor() -> CardCommentAnchorModel:
    return CardCommentAnchorModel(
        exact="stable quote",
        prefix="before",
        suffix="after",
        start_block="A stable quote survives edits",
        end_block="A stable quote survives edits",
        start_path=[2],
        end_path=[2],
    )


def test_anchor_is_exposed_with_the_comment_without_changing_comment_content() -> None:
    anchor = _anchor()
    comment = CardComment(
        card_id=SnowflakeID(1),
        content=EditorContentModel(content="Review this"),
        anchor=anchor.model_dump(),
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


def test_anchor_migration_upgrades_and_downgrades() -> None:
    spec = importlib.util.spec_from_file_location("card_comment_anchor_migration", MIGRATION)
    assert spec and spec.loader
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)

    engine = sa.create_engine("sqlite://")
    with engine.begin() as connection:
        connection.execute(sa.text("CREATE TABLE card_comment (id INTEGER PRIMARY KEY)"))
        migration.op = Operations(MigrationContext.configure(connection))

        migration.upgrade()
        assert "anchor" in {column["name"] for column in sa.inspect(connection).get_columns("card_comment")}

        migration.downgrade()
        assert "anchor" not in {column["name"] for column in sa.inspect(connection).get_columns("card_comment")}
