from starlette.requests import Request
from .Auth import Auth


def test_auth_scope_reads_the_langboard_request_scope_without_starlette_authentication_middleware() -> None:
    """Langboard's own auth middleware is the sole actor authority."""

    actor = object()
    request = Request({"type": "http", "headers": [], "auth": actor})
    dependency = Auth.scope("user")

    assert dependency.dependency(request) is actor
