"""Authenticated board Signal Inbox. No automatic card creation."""

from fastapi import Request
from langboard_shared.core.filter import AuthFilter
from langboard_shared.core.routing import ApiException, AppRouter, JsonResponse
from langboard_shared.core.security.CollaborationChannel import CollaborationChannel
from langboard_shared.domain.models import User
from langboard_shared.domain.services import DomainService
from langboard_shared.security import Auth
from pydantic import BaseModel, ConfigDict, Field, field_validator
from ...apps.SignalInbox import create_signal_card, list_board_signals
from .CardSignalApi import response


@AppRouter.api.get("/board/{project_uid}/signals/inbox", tags=["Board.Apps"])
@AuthFilter.add("user")
def get_signal_inbox(
    project_uid: str,
    after: str | None = None,
    user: User = Auth.scope("user"),
    service: DomainService = DomainService.scope(),
):
    try:
        return response(list_board_signals, service, user, project_uid, after)
    except ValueError:
        raise ApiException.BadRequest_400() from None


class SignalCardForm(BaseModel):
    model_config = ConfigDict(extra="forbid")
    connection_uid: str = Field(pattern=r"^[A-Za-z0-9]{1,11}$")
    resource_uid: str = Field(pattern=r"^[A-Za-z0-9]{1,11}$")
    signal_uid: str = Field(pattern=r"^[A-Za-z0-9]{1,11}$")
    project_column_uid: str = Field(pattern=r"^[A-Za-z0-9]{1,11}$")
    title: str = Field(strict=True)

    @field_validator("title")
    @classmethod
    def valid_title(cls, value):
        value = value.strip()
        if not value or len(value) > 200:
            raise ValueError("Title must contain 1 to 200 characters")
        return value


@AppRouter.api.post("/board/{project_uid}/signals/inbox/card", tags=["Board.Apps"])
@AuthFilter.add("user")
def create_inbox_card(
    request: Request,
    project_uid: str,
    form: SignalCardForm,
    user: User = Auth.scope("user"),
    service: DomainService = DomainService.scope(),
):
    from ...apps.CardSignal import CardSignalConflict
    from ...apps.GitHubManifest import GitHubManifestUnavailable

    try:
        result = create_signal_card(
            service,
            user,
            project_uid,
            **form.model_dump(),
            channel=request.scope.get("collaboration_channel", CollaborationChannel.Api),
        )
        return JsonResponse(content=result, status_code=201 if result["created"] else 200)
    except GitHubManifestUnavailable:
        raise ApiException.NotFound_404() from None
    except CardSignalConflict:
        raise ApiException.Conflict_409() from None
    except ValueError:
        raise ApiException.BadRequest_400() from None
