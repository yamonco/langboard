"""Real block batching preserves point projection and authorized scope."""

from types import SimpleNamespace
from sqlalchemy import create_engine, event
from ....core.db.DbEngine import DbEngine
from ....domain.models import CardContentBlock
from ....infrastructure.repositories.factory.CardContentBlockRepository import CardContentBlockRepository
from .CardContentBlockService import CardContentBlockService


def test_block_batch_uses_one_query_and_matches_point_projection(monkeypatch):
    engine = create_engine("sqlite://")
    CardContentBlock.__table__.create(engine)
    monkeypatch.setattr(DbEngine, "get_main_engine", lambda: engine)
    monkeypatch.setattr(DbEngine, "get_readonly_engine", lambda: engine)
    rows = [
        CardContentBlock(
            id=i * 10 + j,
            card_id=i,
            block_type="code",
            order=0,
            revision=j + 1,
            payload={"language": "python", "code": str(j)},
        )
        for i in range(1, 101)
        for j in range(3)
    ]
    rows += [
        CardContentBlock(id=2001, card_id=999, block_type="code"),
    ]
    with engine.begin() as db:
        db.execute(
            CardContentBlock.__table__.insert(), [{k: getattr(row, k) for k in row.model_fields} for row in rows]
        )
    service = CardContentBlockService(
        lambda _: None, lambda _: None, SimpleNamespace(card_content_block=CardContentBlockRepository(None, None))
    )
    queries = []

    def count(conn, cursor, statement, *args):
        queries.append(statement)

    event.listen(engine, "before_cursor_execute", count)
    try:
        batch = service.api_blocks_by_cards(list(range(1, 101)))
        assert len(queries) == 1
        event.remove(engine, "before_cursor_execute", count)
        assert batch == {i: service.api_blocks_by_card(i) for i in range(1, 101)}
        assert all(len(blocks) == 3 for blocks in batch.values())
        assert [block["revision"] for block in batch[1]] == [1, 2, 3]
        assert 999 not in batch
        assert service.api_blocks_by_cards([]) == {}
    finally:
        engine.dispose()
