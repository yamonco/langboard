"""Read logical reference metadata without resolving or creating credentials."""

from typing import Annotated, Any
from langboard_shared.domain.models import User
from langboard_shared.domain.services import DomainService
from langboard_shared.domain.services.factory.SecretReferenceService import SecretReferenceUnavailable
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
