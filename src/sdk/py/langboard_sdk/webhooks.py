"""Verify native webhook bytes before parsing or executing any business action."""

import re
import time
from collections.abc import Mapping
from hashlib import sha256
from hmac import compare_digest
from hmac import new as hmac_new


class InvalidWebhook(ValueError):
    """A webhook cannot be authenticated; body and secret are never echoed."""


def verify_webhook(body: bytes, headers: Mapping[str, str], secret: str, *, now: int | None = None) -> None:
    """Authenticate exact wire bytes, native v1 headers and a five-minute age.

    This is not duplicate detection or execution authorization. Persist event_id
    atomically with the consumer's work and check current board authority.
    """
    if not isinstance(body, bytes) or len(body) > 1024 * 1024:
        raise InvalidWebhook("Webhook body must be bounded bytes")
    if not isinstance(secret, str) or not secret or len(secret) > 16384:
        raise InvalidWebhook("Webhook signing secret is required")
    selected = {}
    for key, value in headers.items():
        if not isinstance(key, str):
            raise InvalidWebhook("Invalid webhook headers")
        name = key.lower()
        if name not in {"x-langboard-webhook-version", "x-langboard-webhook-timestamp", "x-langboard-webhook-signature"}:
            continue
        if name in selected or not isinstance(value, str) or len(value) > 80:
            raise InvalidWebhook("Invalid webhook headers")
        selected[name] = value
    timestamp = selected.get("x-langboard-webhook-timestamp", "")
    signature = selected.get("x-langboard-webhook-signature", "")
    if selected.get("x-langboard-webhook-version") != "1" or not re.fullmatch(r"[0-9]{1,12}", timestamp):
        raise InvalidWebhook("Unsupported webhook headers")
    if not re.fullmatch(r"v1=[0-9a-f]{64}", signature):
        raise InvalidWebhook("Invalid webhook signature")
    clock = int(time.time()) if now is None else now
    if type(clock) is not int or not -30 <= clock - int(timestamp) <= 300:
        raise InvalidWebhook("Webhook timestamp is outside the accepted window")
    expected = hmac_new(secret.encode("utf-8"), timestamp.encode("ascii") + b"." + body, sha256).hexdigest()
    if not compare_digest(signature[3:], expected):
        raise InvalidWebhook("Invalid webhook signature")
