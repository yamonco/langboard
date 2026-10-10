from datetime import timedelta
from sqlite3 import Connection
from typing import Any, Callable, TypeVar, overload
from ...Env import Env
from ..types import SafeDateTime
from .BaseCache import BaseCache


_TCastReturn = TypeVar("_TCastReturn")


class InMemoryCache(BaseCache):
    @overload
    def get(self, key: str) -> Any | None: ...
    @overload
    def get(self, key: str, caster: Callable[[Any], _TCastReturn]) -> _TCastReturn | None: ...
    def get(self, key: str, caster: Callable[[Any], _TCastReturn] | None = None) -> Any | None:
        self._expire()
        with self._get_cache_db() as conn:
            cursor = conn.execute(
                "SELECT value, expiry FROM cache WHERE key = ? AND expiry > ?",
                (key, int(SafeDateTime.now().timestamp())),
            )
            raw_value, ttl = cursor.fetchone() or (None, None)
            if raw_value is None or ttl is None:
                return None

            value = self._cast_get(raw_value, caster)
        return value

    def has(self, key: str) -> bool:
        self._expire()
        result = False
        with self._get_cache_db() as conn:
            cursor = conn.execute(
                "SELECT 1 FROM cache WHERE key = ? AND expiry > ?", (key, int(SafeDateTime.now().timestamp()))
            )
            result = cursor.fetchone() is not None
        return result

    def set(self, key: str, value: Any, ttl: int = 0) -> None:
        self._expire()
        with self._get_cache_db() as conn:
            casted_value = self._cast_set(value)
            expiry = int((SafeDateTime.now() + timedelta(seconds=ttl)).timestamp())
            conn.execute("REPLACE INTO cache (key, value, expiry) VALUES (?, ?, ?)", (key, casted_value, expiry))
            conn.commit()

    def set_if_absent(self, key: str, value: Any, ttl: int) -> bool:
        if ttl <= 0:
            raise ValueError("Atomic cache entries require a positive TTL")
        self._expire()
        with self._get_cache_db() as conn:
            casted_value = self._cast_set(value)
            expiry = int((SafeDateTime.now() + timedelta(seconds=ttl)).timestamp())
            cursor = conn.execute(
                "INSERT OR IGNORE INTO cache (key, value, expiry) VALUES (?, ?, ?)",
                (key, casted_value, expiry),
            )
            conn.commit()
            return cursor.rowcount == 1

    def delete(self, key: str) -> None:
        self._expire()
        with self._get_cache_db() as conn:
            conn.execute("DELETE FROM cache WHERE key = ?", (key,))
            conn.commit()

    def clear(self) -> None:
        with self._get_cache_db() as conn:
            conn.execute("DELETE FROM cache")
            conn.commit()

    def _expire(self) -> None:
        with self._get_cache_db() as conn:
            conn.execute("DELETE FROM cache WHERE expiry <= ?", (int(SafeDateTime.now().timestamp()),))
            conn.commit()

    def _get_cache_db(self) -> Connection:
        if Env.CACHE_DIR is None:
            raise ValueError("Cache directory is not set")

        Env.CACHE_DIR.mkdir(parents=True, exist_ok=True)
        db_path = Env.CACHE_DIR / "cache.db"
        conn = Connection(db_path)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS cache (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL,
                expiry INTEGER NOT NULL
            )
        """)
        return conn
