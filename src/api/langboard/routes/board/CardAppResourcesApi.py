"""Human configuration of existing generic card resources; never execution authority."""

from fastapi import Request
from langboard_shared.core.db import DbSession
from langboard_shared.core.filter import AuthFilter
from langboard_shared.core.routing import ApiException, AppRouter, JsonResponse
from langboard_shared.core.security.CollaborationChannel import CollaborationChannel
from langboard_shared.core.types import SnowflakeID
from langboard_shared.domain.models import User
from langboard_shared.domain.services import DomainService
from langboard_shared.domain.services.AppGovernance import AppGovernanceDenied
from langboard_shared.domain.services.CardAppGovernance import CardAppOwnershipConflict, _admin_card
from langboard_shared.domain.services.CardAppResources import read_card_app_resources, set_card_app_resources
from langboard_shared.security import Auth
from pydantic import BaseModel, ConfigDict, Field


class CardResourcesForm(BaseModel):
    model_config = ConfigDict(extra="forbid")
    resource_uids: list[str] = Field(max_length=20)
    expected_revision: int | None = Field(default=None, strict=True, ge=1)


def _configure(operation, request, service, actor, project_uid, card_uid, connection_uid, *args):
    try:
        with DbSession.atomic() as db:
            project_id = SnowflakeID.from_short_code(project_uid)
            card_id = SnowflakeID.from_short_code(card_uid)
            connection_id = SnowflakeID.from_short_code(connection_uid)
            # Hold native actor/project/card locks before resolving audience facts.
            try:
                _admin_card(db, actor, project_id, card_id)
            except AppGovernanceDenied:
                raise ApiException.NotFound_404() from None
            channel = request.scope.get("collaboration_channel", CollaborationChannel.Api)
            if service.card.resolve_readable_card(project_uid, card_uid, actor, channel) is None:
                raise ApiException.NotFound_404()
            result = operation(
                actor,
                project_id,
                card_id,
                connection_id,
                *args,
            )
            return JsonResponse(content=result, headers={"Cache-Control": "no-store"})
    except AppGovernanceDenied:
        raise ApiException.Forbidden_403() from None
    except CardAppOwnershipConflict:
        raise ApiException.Conflict_409() from None
    except ValueError:
        raise ApiException.BadRequest_400() from None


@AppRouter.api.get(
    "/board/{project_uid}/card/{card_uid}/apps/connections/{connection_uid}/resources", tags=["Board.Card"]
)
@AuthFilter.add("user")
def read_resources(
    request: Request,
    project_uid: str,
    card_uid: str,
    connection_uid: str,
    user: User = Auth.scope("user"),
    service: DomainService = DomainService.scope(),
):
    return _configure(read_card_app_resources, request, service, user, project_uid, card_uid, connection_uid)


@AppRouter.api.put(
    "/board/{project_uid}/card/{card_uid}/apps/connections/{connection_uid}/resources", tags=["Board.Card"]
)
@AuthFilter.add("user")
def select_resources(
    request: Request,
    project_uid: str,
    card_uid: str,
    connection_uid: str,
    form: CardResourcesForm,
    user: User = Auth.scope("user"),
    service: DomainService = DomainService.scope(),
):
    return _configure(
        set_card_app_resources,
        request,
        service,
        user,
        project_uid,
        card_uid,
        connection_uid,
        form.resource_uids,
        form.expected_revision,
    )
