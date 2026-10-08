"""Explicit evidence attachment, separate from approval and workflow transitions."""

from langboard_shared.core.filter import AuthFilter
from langboard_shared.core.routing import ApiException, AppRouter, JsonResponse
from langboard_shared.domain.models import User
from langboard_shared.domain.services import DomainService
from langboard_shared.security import Auth
from pydantic import BaseModel, ConfigDict, Field
from ...apps.CardSignal import CardSignalConflict, bind_check, read_checks, unlink_check
from ...apps.GitHubManifest import GitHubManifestUnavailable


class CardSignalForm(BaseModel):
    model_config = ConfigDict(extra="forbid")
    connection_uid: str = Field(pattern=r"^[A-Za-z0-9]{1,11}$")
    resource_uid: str = Field(pattern=r"^[A-Za-z0-9]{1,11}$")
    signal_uid: str = Field(pattern=r"^[A-Za-z0-9]{1,11}$")
    source_change_seq: int = Field(strict=True, ge=0)
    expected_revision: int | None = Field(default=None, strict=True, ge=0)


class UnlinkSignalForm(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_revision: int = Field(strict=True, ge=0)


def response(action, *args):
    try:
        return JsonResponse(content=action(*args))
    except GitHubManifestUnavailable:
        raise ApiException.NotFound_404() from None
    except CardSignalConflict:
        raise ApiException.Conflict_409() from None


@AppRouter.api.get("/board/{project_uid}/card/{card_uid}/signals", tags=["Board.Card"])
@AuthFilter.add("user")
def get_card_signals(
    project_uid: str, card_uid: str, user: User = Auth.scope("user"), service: DomainService = DomainService.scope()
):
    return response(read_checks, service, user, project_uid, card_uid)


@AppRouter.api.post("/board/{project_uid}/card/{card_uid}/signals", tags=["Board.Card"])
@AuthFilter.add("user")
def attach_card_signal(
    project_uid: str,
    card_uid: str,
    form: CardSignalForm,
    user: User = Auth.scope("user"),
    service: DomainService = DomainService.scope(),
):
    return response(
        bind_check,
        service,
        user,
        project_uid,
        card_uid,
        form.connection_uid,
        form.resource_uid,
        form.signal_uid,
        form.source_change_seq,
        form.expected_revision,
    )


@AppRouter.api.post("/board/{project_uid}/card/{card_uid}/signals/{binding_uid}/unlink", tags=["Board.Card"])
@AuthFilter.add("user")
def unlink_card_signal(
    project_uid: str,
    card_uid: str,
    binding_uid: str,
    form: UnlinkSignalForm,
    user: User = Auth.scope("user"),
    service: DomainService = DomainService.scope(),
):
    return response(unlink_check, service, user, project_uid, card_uid, binding_uid, form.expected_revision)


@AppRouter.api.get("/board/{project_uid}/card/{card_uid}/signals/resources", tags=["Board.Card"])
@AuthFilter.add("user")
def get_card_signal_resources(
    project_uid: str,
    card_uid: str,
    after: str | None = None,
    user: User = Auth.scope("user"),
    service: DomainService = DomainService.scope(),
):
    from ...apps.CardSignal import list_card_resources

    try:
        return response(list_card_resources, service, user, project_uid, card_uid, after)
    except ValueError:
        raise ApiException.BadRequest_400() from None
