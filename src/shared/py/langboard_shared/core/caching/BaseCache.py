from abc import ABC, abstractmethod
from json import dumps as json_dumps
from json import loads as json_loads
from typing import Any, Callable
from pydantic import BaseModel
from ..utils.Converter import json_default


class BaseCache(ABC):
    @abstractmethod
    def get(self, key: str, caster: Callable[[Any], Any] | None = None) -> Any | None:
        """Gets value from cache by key

        You can provide a cast function to cast the value before returning it.

        You can also provide a coroutine function as the cast function.

        If the cast function raises an exception, None will be returned.

        :param key: Key to get value from cache
        :param cast: Function to cast value to
        """

    @abstractmethod
    def has(self, key: str) -> bool:
        """Checks if key exists in cache

        :param key: Key to check if exists in cache
        """

    @abstractmethod
    def set(self, key: str, value: Any, ttl: int = 0) -> None:
        """Sets value in cache by key

        If value is a Pydantic model, it will call model_dump_json() to serialize the model.

        Otherwise, it will serialize the value to JSON.

        So you must provide serializable values.

        :param key: Key to set value in cache
        :param value: Value to set in cache
        :param ttl: Time to live in seconds
        """

    @abstractmethod
    def set_if_absent(self, key: str, value: Any, ttl: int) -> bool:
        """Atomically set a value with a positive TTL when the key is absent."""

    @abstractmethod
    def delete(self, key: str) -> None:
        """Deletes value from cache by key

        :param key: Key to delete value from cache
        """

    @abstractmethod
    def clear(self) -> None:
        """Deletes all values from cache"""

    def _cast_get(self, raw_value: Any, cast: Callable[[Any], Any] | None) -> Any | None:
        value = json_loads(raw_value)

        if cast is None:
            return value

        try:
            return cast(value)
        except Exception:
            return None

    def _cast_set(self, value: Any) -> str:
        if isinstance(value, BaseModel):
            return value.model_dump_json()
        else:
            return json_dumps(value, default=json_default)
