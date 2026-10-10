"""Read logical reference metadata without resolving or creating credentials."""

from typing import Annotated, Any
from langboard_shared.core.security.CollaborationChannel import CollaborationChannel
from langboard_shared.domain.models import User
from langboard_shared.domain.services import DomainService
from langboard_shared.domain.services.factory.SecretReferenceService import SecretReferenceUnavailable
from mcp.types import InputRequiredResult
from pydantic import Field
from ..mcp_integration import McpTool


@McpTool.add(
    "user",
    description="Read one authorized secret URI's metadata. Never returns credentials or vault locators; no resolve/create operation. Preserve canonical URI for runtime references.",
)
def get_secret_reference_metadata(
    uri: Annotated[str, Field(min_length=1, max_length=320)],
    user: User,
    service: DomainService,
) -> dict[str, Any]:
    try:
        return {"reference": service.secret_reference.get_metadata(user, uri)}
    except (SecretReferenceUnavailable, ValueError):
        raise ValueError("Secret reference unavailable") from None


@McpTool.add(
    "user",
    description="Only on explicit user instruction, issue an authenticated one-use browser URL to create a secret. Never request or accept secret values in chat, tool arguments or form elicitation. The URL grants no access without the same user's web login. Show the URL for user consent; do not open it automatically.",
)
def request_secret_input(
    scope: Annotated[str, Field(pattern=r"^(personal|project|workspace)$")],
    scope_uid: Annotated[str, Field(min_length=1, max_length=11)],
    name: Annotated[str, Field(min_length=1, max_length=256)],
    user: User,
    service: DomainService,
) -> dict[str, Any] | InputRequiredResult:
    from ..secrets.McpSecretInput import request_input
    from ..secrets.SecretInput import begin_input

    try:
        return request_input(
            service,
            user,
            {"operation": "create", "scope": scope, "scope_uid": scope_uid, "name": name},
            lambda: begin_input(service, user, scope, scope_uid, name),
        )
    except (SecretReferenceUnavailable, ValueError):
        raise ValueError("Secret input unavailable") from None


@McpTool.add(
    "user",
    description="Read completion state and secret_ref for one previously requested secret input. Never returns secret material; expired or unauthorized sessions are unavailable.",
)
def get_secret_input_status(
    input_uid: Annotated[str, Field(pattern=r"^[A-Za-z0-9_-]{43}$")],
    user: User,
    service: DomainService,
) -> dict[str, Any]:
    from ..secrets.SecretInput import input_status

    try:
        return input_status(service, user, input_uid)
    except (SecretReferenceUnavailable, ValueError):
        raise ValueError("Secret input unavailable") from None


@McpTool.add(
    "user",
    description="Only on explicit user instruction, issue an authenticated one-use browser URL to replace an existing secret's value. Read its metadata revision first. Never accept secret values in chat or tool arguments. The target reference and revision are fixed; show the URL for user consent.",
)
def request_secret_rotation_input(
    uri: Annotated[str, Field(min_length=1, max_length=320)],
    expected_revision: Annotated[int, Field(strict=True, ge=0)],
    user: User,
    service: DomainService,
) -> dict[str, Any] | InputRequiredResult:
    from ..secrets.McpSecretInput import request_input
    from ..secrets.SecretInput import begin_rotation

    try:
        return request_input(
            service,
            user,
            {"operation": "rotate", "secret_ref": uri, "expected_revision": expected_revision},
            lambda: begin_rotation(service, user, uri, expected_revision),
        )
    except (SecretReferenceUnavailable, ValueError):
        raise ValueError("Secret input unavailable") from None


@McpTool.add(
    "user",
    description="Read a bounded page of one authorized secret reference's audit facts. Never resolves secret material or vault paths. Current authority is checked on every page; reuse next_cursor only for the same reference.",
)
def list_secret_reference_history(
    uri: Annotated[str, Field(min_length=1, max_length=320)],
    user: User,
    service: DomainService,
    limit: Annotated[int, Field(strict=True, ge=1, le=50)] = 25,
    cursor: Annotated[str | None, Field(max_length=11)] = None,
) -> dict[str, Any]:
    try:
        return service.secret_reference.list_audit(
            user, uri, limit=limit, cursor=cursor, channel=CollaborationChannel.Mcp
        )
    except (SecretReferenceUnavailable, ValueError):
        raise ValueError("Secret history unavailable") from None
