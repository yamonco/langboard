import asyncio
from inspect import iscoroutinefunction
from typing import Any, Callable, TypeVar, overload
from redis import Redis
from ...Env import Env
from .BaseCache import BaseCache


_TCastReturn = TypeVar("_TCastReturn")


class RedisCache(BaseCache):
    def __init__(self):
        super().__init__()
        self._cache = Redis.from_url(Env.CACHE_URL, decode_responses=True)

    @overload
    def get(self, key: str) -> Any | None: ...
    @overload
    def get(self, key: str, caster: Callable[[Any], _TCastReturn]) -> _TCastReturn | None: ...
    def get(self, key: str, caster: Callable[[Any], _TCastReturn] | None = None) -> Any | None:
        raw_value = self.__run_redis_method("get", key)
        if raw_value is None:
            return None

        value = self._cast_get(raw_value, caster)
        return value

    def has(self, key: str) -> bool:
        return self.__run_redis_method("exists", key)

    def set(self, key: str, value: Any, ttl: int = 0) -> None:
        casted_value = self._cast_set(value)
        self.__run_redis_method("set", key, casted_value, ex=ttl if ttl > 0 else None)

    def set_if_absent(self, key: str, value: Any, ttl: int) -> bool:
        if ttl <= 0:
            raise ValueError("Atomic cache entries require a positive TTL")
        casted_value = self._cast_set(value)
        return bool(self.__run_redis_method("set", key, casted_value, ex=ttl, nx=True))

    def delete(self, key: str) -> None:
        if self.__run_redis_method("exists", key):
            self.__run_redis_method("delete", key)

    def clear(self) -> None:
        self.__run_redis_method("flushdb")

    def __run_redis_method(self, command: str, *args: Any, **kwargs) -> Any:
        method = getattr(self._cache, command)
        if iscoroutinefunction(method):
            return asyncio.run(method(*args, **kwargs))
        else:
            return method(*args, **kwargs)
