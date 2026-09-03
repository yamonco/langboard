from random import getrandbits
from threading import Lock
from time import time
from typing import Any
from ..utils.String import BASE62_ALPHABET


class SnowflakeID(int):
    FIXED_SHORT_CODE_LENGTH = 11
    MAX_VALUE = 2**63 - 1
    EPOCH = 1704067200000  # 2024-01-01 00:00:00 UTC
    _lock = Lock()
    _sequence = 0
    _last_timestamp = -1

    def __new__(cls, value: int | str | None = None):
        if value is not None:
            if isinstance(value, str):
                try:
                    value = int(value)
                except Exception:
                    value = 0
            return super().__new__(cls, value)

        machine_id = SnowflakeID.__get_machine_id()

        with cls._lock:
            current_timestamp = cls._current_millis()

            if current_timestamp == cls._last_timestamp:
                cls._sequence = (cls._sequence + 1) & 0xFFF
                if cls._sequence == 0:
                    current_timestamp = cls._wait_next_millis(current_timestamp)
            else:
                cls._sequence = 0

            cls._last_timestamp = current_timestamp

            snowflake_value = ((current_timestamp - SnowflakeID.EPOCH) << 22) | (machine_id << 12) | getrandbits(20)

        return super().__new__(cls, snowflake_value)

    @staticmethod
    def from_short_code(short_code: str) -> "SnowflakeID":
        if not short_code or len(short_code) != SnowflakeID.FIXED_SHORT_CODE_LENGTH:
            return SnowflakeID(0)
        decoded_int = SnowflakeID.__base62_decode(short_code)
        original_value = SnowflakeID.__feistel_unshuffle(decoded_int)
        return SnowflakeID(original_value if original_value <= SnowflakeID.MAX_VALUE else 0)

    @classmethod
    def _current_millis(cls):
        return int(time() * 1000)

    @classmethod
    def _wait_next_millis(cls, last_ts: int):
        ts = cls._current_millis()
        while ts <= last_ts:
            ts = cls._current_millis()
        return ts

    @classmethod
    def __get_validators__(cls):
        yield cls.validate

    @classmethod
    def __get_pydantic_core_schema__(cls, source_type, handler):
        from pydantic_core import core_schema

        return core_schema.with_info_plain_validator_function(
            cls.validate,
            json_schema_input_schema=core_schema.union_schema(
                [core_schema.int_schema(), core_schema.str_schema(), core_schema.none_schema()]
            ),
        )

    @classmethod
    def __get_pydantic_json_schema__(cls, core_schema, handler):
        return {"type": "string"}

    @classmethod
    def validate(cls, value: Any, _, **kwargs):
        if value is None:
            return cls()
        if isinstance(value, SnowflakeID):
            return value
        if isinstance(value, int):
            return cls(value)
        if isinstance(value, str):
            if len(value) == cls.FIXED_SHORT_CODE_LENGTH:
                return cls.from_short_code(value)
            try:
                return cls(int(value))
            except ValueError:
                pass
        raise TypeError("SnowflakeID must be an integer or None")

    def __str__(self):
        return str(int(self))

    def __repr__(self):
        return f"SnowflakeID({int(self)})"

    def to_short_code(self) -> str:
        mixed_value = SnowflakeID.__feistel_shuffle(int(self))
        return SnowflakeID.__base62_encode(mixed_value)

    @staticmethod
    def __base62_encode(n: int) -> str:
        s = []
        while n > 0:
            n, r = divmod(n, 62)
            s.append(BASE62_ALPHABET[r])
        return "".join(reversed(s)).rjust(SnowflakeID.FIXED_SHORT_CODE_LENGTH, BASE62_ALPHABET[0])

    @staticmethod
    def __base62_decode(s: str) -> int:
        n = 0
        for c in s:
            n = n * 62 + BASE62_ALPHABET.index(c)
        return n

    @staticmethod
    def __feistel_shuffle(x: int, rounds: int = 4) -> int:
        left = x >> 32
        right = x & 0xFFFFFFFF
        for i in range(rounds):
            left, right = right, left ^ ((right * SnowflakeID.EPOCH + i) & 0xFFFFFFFF)
        return (left << 32) | right

    @staticmethod
    def __feistel_unshuffle(x: int, rounds: int = 4) -> int:
        left = x >> 32
        right = x & 0xFFFFFFFF
        for i in reversed(range(rounds)):
            left, right = right ^ ((left * SnowflakeID.EPOCH + i) & 0xFFFFFFFF), left
        return (left << 32) | right

    @staticmethod
    def __get_machine_id() -> int:
        from hashlib import sha256
        from socket import gethostname
        from uuid import getnode

        modulo = 2**10
        mac = str(getnode())
        hostname = gethostname()
        raw = mac + hostname
        digest = sha256(raw.encode()).digest()
        int_val = int.from_bytes(digest, "little")
        return int_val % modulo
