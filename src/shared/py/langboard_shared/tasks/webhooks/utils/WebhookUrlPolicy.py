from asyncio import to_thread
from dataclasses import dataclass
from ipaddress import ip_address
from socket import SOCK_STREAM, getaddrinfo
from urllib.parse import urlsplit, urlunsplit


_ALLOWED_SCHEMES = frozenset({"http", "https"})
_ALLOWED_PORTS = frozenset({80, 443})
MAX_WEBHOOK_URL_LENGTH = 2048


@dataclass(frozen=True)
class ResolvedWebhookTarget:
    url: str
    host_header: str
    sni_hostname: str


def validate_webhook_url(url: str) -> str:
    """Normalize a webhook URL and reject obvious SSRF destinations."""

    normalized = url.strip()
    if len(normalized) > MAX_WEBHOOK_URL_LENGTH:
        raise ValueError("Webhook URL is too long")
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


async def ensure_public_webhook_url(url: str) -> ResolvedWebhookTarget:
    """Resolve and pin a webhook target to the public address that was checked."""

    normalized = validate_webhook_url(url)
    parsed = urlsplit(normalized)
    parsed_hostname = parsed.hostname
    if parsed_hostname is None:
        raise ValueError("Webhook URL host is missing")
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    addresses = await to_thread(getaddrinfo, parsed_hostname, port, 0, SOCK_STREAM)
    if not addresses:
        raise ValueError("Webhook URL host did not resolve")
    resolved_ips = [ip_address(address[4][0]) for address in addresses]
    for resolved_ip in resolved_ips:
        if not resolved_ip.is_global:
            raise ValueError("Webhook URL resolved to a private network")

    hostname = parsed_hostname.encode("idna").decode("ascii")
    try:
        original_address = ip_address(hostname)
    except ValueError:
        host_header_name = hostname
    else:
        host_header_name = f"[{hostname}]" if original_address.version == 6 else hostname
    resolved_ip = resolved_ips[0]
    connect_host = f"[{resolved_ip}]" if resolved_ip.version == 6 else str(resolved_ip)
    connect_netloc = f"{connect_host}:{parsed.port}" if parsed.port is not None else connect_host
    host_header = f"{host_header_name}:{parsed.port}" if parsed.port is not None else host_header_name
    return ResolvedWebhookTarget(
        url=urlunsplit((parsed.scheme, connect_netloc, parsed.path, parsed.query, "")),
        host_header=host_header,
        sni_hostname=hostname,
    )
