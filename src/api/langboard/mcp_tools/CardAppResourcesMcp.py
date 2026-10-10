"""Explicit human configuration; app resource consent never grants execution."""

from typing import Annotated, Any
from fastmcp.exceptions import ToolError
from langboard_shared.core.security.CollaborationChannel import CollaborationChannel
from langboard_shared.domain.models import User
from langboard_shared.domain.services import DomainService
from langboard_shared.domain.services.AppGovernance import AppGovernanceDenied
from langboard_shared.domain.services.CardAppGovernance import CardAppOwnershipConflict
from langboard_shared.domain.services.CardAppResources import (
    configure_card_app_resources,
    read_card_app_resources,
    set_card_app_resources,
)
from pydantic import Field
from ..mcp_integration import McpTool


Uid = Annotated[str, Field(pattern=r"^[A-Za-z0-9]{11}$")]


def _configure(operation, service, user, project_uid, card_uid, connection_uid, *args):
    try:
        return configure_card_app_resources(
            operation, service, user, project_uid, card_uid, connection_uid, CollaborationChannel.Mcp, *args
        )
    except AppGovernanceDenied:
        raise ToolError("Card resource configuration unavailable") from None
    except CardAppOwnershipConflict:
        raise ToolError(
            "Card resource selection changed; read current revision before another explicit update"
        ) from None


@McpTool.add(
    "user",
    description="Read card app resource selection and revision under current administrator/connection ownership. No credentials or execution authority.",
)
def get_card_app_resources(
    project_uid: Uid, card_uid: Uid, connection_uid: Uid, user: User, service: DomainService
) -> dict[str, Any]:
    return _configure(read_card_app_resources, service, user, project_uid, card_uid, connection_uid)


@McpTool.add(
    "user",
    description="Only on explicit user instruction, replace card app resource selection; max 20 distinct UIDs. Read revision first. Empty list clears. Never retry an unknown result automatically; read back. Does not grant consent, execution or workflow changes.",
)
def set_card_app_resource_selection(
    project_uid: Uid,
    card_uid: Uid,
    connection_uid: Uid,
    resource_uids: Annotated[list[Uid], Field(max_length=20)],
    expected_revision: Annotated[int | None, Field(strict=True, ge=1)],
    user: User,
    service: DomainService,
) -> dict[str, Any]:
    return _configure(
        set_card_app_resources, service, user, project_uid, card_uid, connection_uid, resource_uids, expected_revision
    )
