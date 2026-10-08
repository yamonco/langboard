"""Authenticated board Signal Inbox. No automatic card creation."""

from langboard_shared.core.filter import AuthFilter
from langboard_shared.core.routing import ApiException, AppRouter
from langboard_shared.domain.models import User
from langboard_shared.domain.services import DomainService
from langboard_shared.security import Auth
from ...apps.SignalInbox import list_board_signals
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
