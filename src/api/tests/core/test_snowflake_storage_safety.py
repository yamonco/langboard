"""Generated IDs retain compatibility; the database arbitrates worker collisions."""

import importlib
import multiprocessing
import os
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4
import pytest
from langboard_shared.core.db import DbSession
from langboard_shared.core.types import SnowflakeID
from langboard_shared.domain.models import User
from sqlalchemy import create_engine, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session


module = importlib.import_module("langboard_shared.core.types.SnowflakeID")
db_module = importlib.import_module("langboard_shared.core.db.DbSession")


@pytest.fixture
def fixed_clock(monkeypatch):
    monkeypatch.setattr(SnowflakeID, "_last_timestamp", -1)
    monkeypatch.setattr(SnowflakeID, "_sequence", 0)
    monkeypatch.setattr(SnowflakeID, "_machine_id", 950)
    monkeypatch.setattr(SnowflakeID, "_current_millis", classmethod(lambda cls: cls.EPOCH + 100000))


def test_same_millisecond_threads_sequence_overflow_and_short_codes(fixed_clock):
    with ThreadPoolExecutor(max_workers=8) as pool:
        values = list(pool.map(lambda _: SnowflakeID(), range(8193)))
    assert len(set(values)) == len(values)
    assert {(int(value) >> 12) & 0x3FF for value in values} == {950}
    assert {int(value) >> 22 for value in values} == {100000, 100001, 100002}
    assert all(SnowflakeID.from_short_code(value.to_short_code()) == value for value in values)
    for value in (0, 1, 123456789, SnowflakeID.MAX_VALUE):
        assert SnowflakeID.from_short_code(SnowflakeID(value).to_short_code()) == value


def test_clock_rollback_preserves_last_sequence(fixed_clock, monkeypatch):
    first = SnowflakeID()
    monkeypatch.setattr(SnowflakeID, "_current_millis", classmethod(lambda cls: cls.EPOCH + 99999))
    assert SnowflakeID() == first + 1


@pytest.mark.parametrize("timestamp", [SnowflakeID.EPOCH - 1, SnowflakeID.EPOCH + 2**41])
def test_timestamp_outside_signed_range_is_rejected(fixed_clock, monkeypatch, timestamp):
    monkeypatch.setattr(SnowflakeID, "_current_millis", classmethod(lambda cls: timestamp))
    with pytest.raises(OverflowError):
        SnowflakeID()


def test_fork_discards_inherited_lock_and_node_identity(fixed_clock):
    old_lock = SnowflakeID._lock
    module._reset_after_fork()
    assert SnowflakeID._lock is not old_lock
    assert SnowflakeID._machine_id is None
    assert SnowflakeID._last_timestamp == -1
    assert SnowflakeID._sequence == 0


@pytest.fixture(params=["sqlite", "postgresql"])
def storage_engine(request):
    admin = None
    schema = None
    if request.param == "postgresql":
        url = os.getenv("LANGBOARD_TEST_DATABASE_URL")
        if not url:
            pytest.skip("Dedicated PostgreSQL proof URL not set")
        admin = create_engine(url)
        schema = f"snowflake_{uuid4().hex}"
        with admin.begin() as connection:
            connection.execute(text(f"CREATE SCHEMA {schema}"))
        engine = create_engine(url, connect_args={"options": f"-csearch_path={schema}"})
    else:
        engine = create_engine("sqlite://")
    User.__table__.create(engine)
    with engine.begin() as connection:
        connection.execute(text('CREATE UNIQUE INDEX fixture_email_unique ON "user" (email)'))
    try:
        yield engine
    finally:
        engine.dispose()
        if admin:
            with admin.begin() as connection:
                connection.execute(text(f"DROP SCHEMA {schema} CASCADE"))
            admin.dispose()


def _forked_allocate(pipe):
    pipe.send(int(SnowflakeID()))
    pipe.close()


@pytest.mark.skipif("fork" not in multiprocessing.get_all_start_methods(), reason="No fork support")
def test_real_fork_while_parent_lock_is_held(fixed_clock):
    context = multiprocessing.get_context("fork")
    parent, child = context.Pipe(duplex=False)
    SnowflakeID._lock.acquire()
    process = context.Process(target=_forked_allocate, args=(child,))
    try:
        process.start()
        assert parent.poll(5), "Child inherited a locked allocator"
        value = parent.recv()
        assert value > 0
        process.join(5)
        assert process.exitcode == 0
    finally:
        SnowflakeID._lock.release()
        if process.is_alive():
            process.terminate()
            process.join(5)
        parent.close()
        child.close()


def make_user(email):
    return User(firstname="ID", lastname="Fixture", email=email, password="test-only")


def test_database_retries_only_id_conflicts_and_keeps_transaction_usable(monkeypatch, storage_engine):
    engine = storage_engine
    identifiers = iter([1, 1, 2, 3])
    monkeypatch.setattr(
        db_module, "SnowflakeID", lambda *args: SnowflakeID(args[0]) if args else SnowflakeID(next(identifiers))
    )
    try:
        with Session(engine) as session, session.begin():
            db = DbSession(session, readonly=False)
            first, second = make_user("first@example.invalid"), make_user("second@example.invalid")
            db.insert(first)
            db.insert(second)
            assert [first.id, second.id] == [1, 2]
            assert len(session.execute(select(User.__table__)).all()) == 2
            with pytest.raises(IntegrityError), session.begin_nested():
                db.insert(make_user("first@example.invalid"))
            assert len(session.execute(select(User.__table__)).all()) == 2
    finally:
        engine.dispose()


def test_id_allocation_exhaustion_preserves_existing_row_and_resets_new_model(monkeypatch, storage_engine):
    engine = storage_engine
    monkeypatch.setattr(db_module, "SnowflakeID", lambda *args: SnowflakeID(args[0] if args else 1))
    try:
        with Session(engine) as session, session.begin():
            db = DbSession(session, readonly=False)
            db.insert(make_user("first@example.invalid"))
            second = make_user("second@example.invalid")
            with pytest.raises(RuntimeError, match="allocation exhausted"):
                db.insert(second)
            assert second.id == 0
            assert len(session.execute(select(User.__table__)).all()) == 1
    finally:
        engine.dispose()


def _persist_worker_batch(database_url, worker, queue):
    SnowflakeID._last_timestamp = -1
    SnowflakeID._sequence = 0
    SnowflakeID._machine_id = 950
    SnowflakeID._current_millis = classmethod(lambda cls: cls.EPOCH + 100000)
    engine = create_engine(database_url)
    try:
        with Session(engine) as session, session.begin():
            db = DbSession(session, readonly=False)
            users = [make_user(f"worker-{worker}-{index}@example.invalid") for index in range(8)]
            db.insert_all(users)
        queue.put([int(user.id) for user in users])
    finally:
        engine.dispose()


def test_independent_processes_with_same_node_and_clock_persist_unique_rows(tmp_path):
    url = f"sqlite:///{tmp_path / 'worker-ids.sqlite'}"
    engine = create_engine(url)
    User.__table__.create(engine)
    context = multiprocessing.get_context("spawn")
    queue = context.Queue()
    workers = [context.Process(target=_persist_worker_batch, args=(url, worker, queue)) for worker in range(4)]
    try:
        for worker in workers:
            worker.start()
        batches = [queue.get(timeout=15) for _ in workers]
        for worker in workers:
            worker.join(15)
            assert worker.exitcode == 0
        identifiers = [value for batch in batches for value in batch]
        assert len(identifiers) == len(set(identifiers)) == 32
        with engine.connect() as connection:
            assert len(connection.execute(select(User.__table__)).all()) == 32
    finally:
        for worker in workers:
            if worker.is_alive():
                worker.terminate()
                worker.join(5)
        queue.close()
        queue.join_thread()
        engine.dispose()
