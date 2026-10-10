from typing import Any, Callable, TypeVar, overload
from ...Env import Env
from ..utils.decorators import class_instance, thread_safe_singleton
from .BaseCache import BaseCache
from .InMemoryCache import InMemoryCache
from .RedisCache import RedisCache


_TCastReturn = TypeVar("_TCastReturn")


@class_instance()
@thread_safe_singleton
class Cache(BaseCache):
    def __init__(self):
        if Env.CACHE_TYPE == "redis":
            self._cache: BaseCache = RedisCache()
        else:
            self._cache: BaseCache = InMemoryCache()

    @overload
    def get(self, key: str) -> Any | None: ...
    @overload
    def get(self, key: str, caster: Callable[[Any], _TCastReturn]) -> _TCastReturn | None: ...
    def get(self, key: str, caster: Callable[[Any], _TCastReturn] | None = None) -> Any | None:
        return self._cache.get(key, caster)

    def has(self, key: str) -> bool:
        return self._cache.has(key)

    @overload
    def set(self, key: str, value: Any) -> None: ...
    @overload
    def set(self, key: str, value: Any, ttl: int) -> None: ...
    def set(self, key: str, value: Any, ttl: int = 0) -> None:
        self._cache.set(key, value, ttl)

    def set_if_absent(self, key: str, value: Any, ttl: int) -> bool:
        return self._cache.set_if_absent(key, value, ttl)

    def delete(self, key: str) -> None:
        self._cache.delete(key)

    def clear(self) -> None:
        self._cache.clear()
