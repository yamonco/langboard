from asyncio import to_thread
from ipaddress import ip_address
from socket import SOCK_STREAM, getaddrinfo
from urllib.parse import urlsplit


_ALLOWED_SCHEMES = frozenset({"http", "https"})
_ALLOWED_PORTS = frozenset({80, 443})


def validate_webhook_url(url: str) -> str:
    """Normalize a webhook URL and reject obvious SSRF destinations."""

    normalized = url.strip()
    try:
        parsed = urlsplit(normalized)
        port = parsed.port
    except ValueError as error:
        raise ValueError("Webhook URL is invalid") from error
    if parsed.scheme not in _ALLOWED_SCHEMES or not parsed.hostname:
        raise ValueError("Webhook URL must use HTTP or HTTPS")
    if parsed.username or parsed.password or parsed.fragment:
        raise ValueError("Webhook URL credentials and fragments are not allowed")
    if port is not None and port not in _ALLOWED_PORTS:
        raise ValueError("Webhook URL port is not allowed")
    hostname = parsed.hostname.rstrip(".").lower()
    if hostname == "localhost" or hostname.endswith((".localhost", ".local", ".internal")):
        raise ValueError("Webhook URL host is not allowed")
    try:
        address = ip_address(hostname)
    except ValueError:
        return normalized
    if not address.is_global:
        raise ValueError("Webhook URL must not target a private network")
    return normalized


async def ensure_public_webhook_url(url: str) -> str:
    """Resolve a webhook immediately before delivery and reject non-public IPs."""

    normalized = validate_webhook_url(url)
    parsed = urlsplit(normalized)
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    addresses = await to_thread(getaddrinfo, parsed.hostname, port, 0, SOCK_STREAM)
    if not addresses:
        raise ValueError("Webhook URL host did not resolve")
    for address in addresses:
        resolved_ip = ip_address(address[4][0])
        if not resolved_ip.is_global:
            raise ValueError("Webhook URL resolved to a private network")
    return normalized
