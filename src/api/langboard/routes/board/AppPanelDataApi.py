"""Generic read bridge for independently registered app panels; no provider credentials."""

from fastapi import Request
from langboard_shared.core.db import DbSession
from langboard_shared.core.filter import AuthFilter
from langboard_shared.core.routing import ApiException, AppRouter, JsonResponse
from langboard_shared.core.security.CollaborationChannel import CollaborationChannel
from langboard_shared.domain.models import User
from langboard_shared.domain.services import DomainService
from langboard_shared.domain.services.AppPanel import get_panel
from langboard_shared.security import Auth
from pydantic import BaseModel, ConfigDict, Field
from ...apps.GitHubManifest import GitHubManifestUnavailable
from ...apps.SignalInbox import list_board_signals


class PanelSignalsForm(BaseModel):
    model_config = ConfigDict(extra="forbid")
    app_revision: str = Field(pattern=r"^[0-9a-f]{64}$")
    binding_revision: str = Field(pattern=r"^[0-9a-f]{64}$")
    # Installed adapter support is validated by the authorized native read.
    provider: str = Field(pattern=r"^[a-z][a-z0-9_-]{0,31}$")
    after: str | None = Field(default=None, pattern=r"^[A-Za-z0-9]{1,11}$")


@AppRouter.api.post("/board/{project_uid}/apps/{app_key}/panel/signals", tags=["Board.Apps"])
@AuthFilter.add("user")
def read_panel_signals(request: Request, project_uid: str, app_key: str, form: PanelSignalsForm,
                       user: User = Auth.scope("user"), service: DomainService = DomainService.scope()):
    with DbSession.atomic():
        # Lock current authority and consent until the native bounded read finishes.
        panel = get_panel(service.workflow_stage, user, project_uid, app_key, lock=True)
        if panel is None or "signals.read" not in panel["granted_capabilities"]:
            raise ApiException.NotFound_404()
        if panel["app_revision"] != form.app_revision or panel["binding_revision"] != form.binding_revision:
            raise ApiException.Conflict_409()
        try:
            result = list_board_signals(service, user, project_uid, form.after,
                channel=request.scope.get("collaboration_channel", CollaborationChannel.Api), provider=form.provider, page_size=10)
        except GitHubManifestUnavailable:
            raise ApiException.NotFound_404() from None
        except ValueError:
            raise ApiException.BadRequest_400() from None
        return JsonResponse(content=result, headers={"Cache-Control": "no-store"})
