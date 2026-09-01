import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from langboard_shared.Env import Env
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from psycopg import AsyncConnection
from psycopg.rows import DictRow, TupleRow, dict_row
from psycopg_pool import AsyncConnectionPool


_checkpoint_setup_done = False
_checkpoint_setup_lock = asyncio.Lock()
_checkpoint_pool: AsyncConnectionPool[AsyncConnection[DictRow]] | None = None
_thread_lock_pool: AsyncConnectionPool[AsyncConnection[TupleRow]] | None = None
_CHECKPOINT_SETUP_LOCK_ID = 473918502


def _is_postgres_database_url(database_url: str) -> bool:
    return database_url.startswith(("postgresql://", "postgres://"))


async def _setup_checkpointer_once(saver: AsyncPostgresSaver) -> None:
    global _checkpoint_setup_done
    if _checkpoint_setup_done:
        return

    async with _checkpoint_setup_lock:
        if _checkpoint_setup_done:
            return

        async with await AsyncConnection.connect(Env.MAIN_DATABASE_URL, autocommit=True) as connection:
            async with connection.cursor() as cursor:
                await cursor.execute("SELECT pg_advisory_lock(%s)", (_CHECKPOINT_SETUP_LOCK_ID,))
                try:
                    await saver.setup()
                finally:
                    await cursor.execute("SELECT pg_advisory_unlock(%s)", (_CHECKPOINT_SETUP_LOCK_ID,))

        _checkpoint_setup_done = True


@asynccontextmanager
async def open_graph_checkpointer(*, enabled: bool = True) -> AsyncIterator[AsyncPostgresSaver | None]:
    if not enabled or not _is_postgres_database_url(Env.MAIN_DATABASE_URL):
        yield None
        return

    pool = await _get_checkpoint_pool()
    saver = AsyncPostgresSaver(pool)
    await _setup_checkpointer_once(saver)
    yield saver


@asynccontextmanager
async def lock_graph_thread(thread_id: str) -> AsyncIterator[None]:
    pool = await _get_thread_lock_pool()
    async with pool.connection() as connection:
        async with connection.transaction():
            async with connection.cursor() as cursor:
                await cursor.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))", (thread_id,))
                yield


async def close_graph_checkpointer() -> None:
    global _checkpoint_pool, _checkpoint_setup_done, _thread_lock_pool
    async with _checkpoint_setup_lock:
        if _checkpoint_pool is not None:
            await _checkpoint_pool.close()
            _checkpoint_pool = None
        if _thread_lock_pool is not None:
            await _thread_lock_pool.close()
            _thread_lock_pool = None
        _checkpoint_setup_done = False


async def _get_checkpoint_pool() -> AsyncConnectionPool[AsyncConnection[DictRow]]:
    global _checkpoint_pool
    if _checkpoint_pool is not None:
        return _checkpoint_pool

    async with _checkpoint_setup_lock:
        if _checkpoint_pool is None:
            pool: AsyncConnectionPool[AsyncConnection[DictRow]] = AsyncConnectionPool(
                Env.MAIN_DATABASE_URL,
                min_size=1,
                max_size=10,
                open=False,
                kwargs={
                    "autocommit": True,
                    "prepare_threshold": 0,
                    "row_factory": dict_row,
                },
            )
            await pool.open(wait=True)
            _checkpoint_pool = pool
    assert _checkpoint_pool is not None
    return _checkpoint_pool


async def _get_thread_lock_pool() -> AsyncConnectionPool[AsyncConnection[TupleRow]]:
    global _thread_lock_pool
    if _thread_lock_pool is not None:
        return _thread_lock_pool

    async with _checkpoint_setup_lock:
        if _thread_lock_pool is None:
            pool: AsyncConnectionPool[AsyncConnection[TupleRow]] = AsyncConnectionPool(
                Env.MAIN_DATABASE_URL,
                min_size=0,
                max_size=2,
                open=False,
                kwargs={"autocommit": True, "prepare_threshold": 0},
            )
            await pool.open()
            _thread_lock_pool = pool
    assert _thread_lock_pool is not None
    return _thread_lock_pool
