"""Scoped app automation creates external issues in an approved native Backlog."""

from fastapi import Header
from langboard_shared.core.routing import ApiException, AppRouter, JsonResponse
from langboard_shared.core.types import SnowflakeID
from langboard_shared.domain.services.AppCardCreation import AppCardCreationConflict, create_app_card
from langboard_shared.domain.services.AppGovernance import AppGovernanceDenied
from pydantic import BaseModel, ConfigDict, Field


class AppCardCreationBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    resource_uid: str = Field(strict=True, pattern=r"^[A-Za-z0-9]{11}$")
    external_id: str = Field(strict=True, min_length=1, max_length=200)
    title: str = Field(strict=True, min_length=1, max_length=200)
    description: str = Field(strict=True, default="", max_length=100000)
    presentation: dict | None = None


@AppRouter.api.post("/apps/v1/boards/{project_uid}/cards", tags=["App.Cards"])
def create_external_app_card(
    project_uid: str, body: AppCardCreationBody, authorization: str = Header(default="", max_length=256)
) -> JsonResponse:
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer":
        raise ApiException.Unauthorized_401()
    try:
        result = create_app_card(
            token,
            SnowflakeID.from_short_code(project_uid),
            SnowflakeID.from_short_code(body.resource_uid),
            body.external_id,
            body.title,
            description=body.description,
            presentation=body.presentation,
        )
    except AppGovernanceDenied as exc:
        raise ApiException.Forbidden_403() from exc
    except AppCardCreationConflict as exc:
        raise ApiException.Conflict_409() from exc
    except ValueError as exc:
        raise ApiException.BadRequest_400() from exc
    return JsonResponse(
        content=result, status_code=201 if result["created"] else 200, headers={"Cache-Control": "no-store"}
    )
