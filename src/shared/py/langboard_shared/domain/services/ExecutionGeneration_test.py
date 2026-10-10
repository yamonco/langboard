from sqlalchemy import create_engine, event, text
from ...core.db.DbEngine import DbEngine
from .ExecutionGeneration import execution_generations


def test_generation_batch_reads_current_primary_fence_and_only_requested_live_cards(monkeypatch):
    engine = create_engine("sqlite://")
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE card (id INTEGER PRIMARY KEY, deleted_at TEXT)"))
        connection.execute(
            text(
                "CREATE TABLE card_execution_generation (card_id INTEGER PRIMARY KEY, execution_generation INTEGER NOT NULL)"
            )
        )
        connection.execute(text("INSERT INTO card VALUES (1,NULL),(2,NULL),(3,NULL),(4,'deleted')"))
        connection.execute(text("INSERT INTO card_execution_generation VALUES (1,3),(3,99),(4,5)"))
    monkeypatch.setattr(DbEngine, "get_main_engine", lambda: engine)

    def refuse_replica():
        raise AssertionError("Generation fences must read the primary")

    monkeypatch.setattr(DbEngine, "get_readonly_engine", refuse_replica)
    statements = []
    event.listen(engine, "before_cursor_execute", lambda *args: statements.append(args[2]))
    assert execution_generations([1, 2, 4, 999]) == {1: 3, 2: 0}
    assert len(statements) == 1
    with engine.begin() as connection:
        connection.execute(text("UPDATE card_execution_generation SET execution_generation=4 WHERE card_id=1"))
    assert execution_generations([1]) == {1: 4}
    before = len(statements)
    assert execution_generations([]) == {}
    assert len(statements) == before
