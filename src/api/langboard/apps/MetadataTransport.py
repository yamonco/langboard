"""Approved self-hosted metadata transport; bounded reads without redirects."""

import json
from time import monotonic
from urllib.parse import urlsplit
import httpx
from langboard_shared.Env import Env


class MetadataUnavailable(Exception):
    pass


def approved_instance(value):
    """Operator-approved exact bases allow public and self-hosted instances."""
    if not isinstance(value, str) or len(value) > 2048:
        raise ValueError("Invalid App instance")
    parsed = urlsplit(value)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
        or "%" in value
        or "\\" in value
        or any(ord(char) < 33 for char in value)
        or any(part in {".", ".."} for part in parsed.path.split("/"))
    ):
        raise ValueError("Invalid App instance")
    try:
        parsed.port
    except ValueError:
        raise ValueError("Invalid App instance") from None
    normalized = value.rstrip("/")
    approved = {
        item.strip().rstrip("/")
        for item in Env.get_from_env("APP_CONNECTION_ALLOWED_BASE_URLS", "").split(",")
        if item.strip()
    }
    if normalized not in approved:
        raise ValueError("Instance must be approved in APP_CONNECTION_ALLOWED_BASE_URLS")
    return normalized


def read_json(base, path, headers, params=None):
    """Caller owns endpoint selection; raw provider responses never reach clients."""
    # Check elapsed budget between reads; one blocking read may use its 15s timeout.
    deadline = monotonic() + 15
    with httpx.Client(timeout=15, follow_redirects=False, trust_env=False) as client:
        with client.stream("GET", base + path, headers=headers, params=params) as response:
            if response.status_code != 200 or monotonic() >= deadline:
                raise MetadataUnavailable()
            body = bytearray()
            for chunk in response.iter_bytes():
                if monotonic() >= deadline or len(body) + len(chunk) > 262144:
                    raise MetadataUnavailable()
                body.extend(chunk)
            if monotonic() >= deadline:
                raise MetadataUnavailable()
            try:
                return json.loads(body), response.links
            except (ValueError, UnicodeError, RecursionError):
                raise MetadataUnavailable() from None
