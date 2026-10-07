"""KMS wraps a short key; existing Encryptor protects arbitrary credential text."""

import json
import secrets
from collections.abc import Callable
from ...utils.Encryptor import Encryptor


PREFIX = "langboard-secret-v1:"


def seal_secret(value: str, wrap_key: Callable[[str], str]) -> str:
    key = secrets.token_urlsafe(32)
    return PREFIX + json.dumps({"key": wrap_key(key), "payload": Encryptor.encrypt(value, key)}, separators=(",", ":"))


def open_secret(locator: str, unwrap_key: Callable[[str], str]) -> str:
    try:
        envelope = json.loads(locator[len(PREFIX) :])
        if not isinstance(envelope, dict) or set(envelope) != {"key", "payload"}:
            raise ValueError()
        if any(not isinstance(envelope[field], str) or not envelope[field] for field in envelope):
            raise ValueError()
        # Only legacy ciphertext is accepted as a wrapped key; no recursive envelope.
        if envelope["key"].startswith(PREFIX):
            raise ValueError()
        key = unwrap_key(envelope["key"])
        result = Encryptor.decrypt(envelope["payload"], key)
        if not result:
            raise ValueError()
        return result
    except (ValueError, TypeError, KeyError):
        raise ValueError("Invalid secret envelope") from None
