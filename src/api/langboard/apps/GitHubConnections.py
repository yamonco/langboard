"""Owner-scoped reusable Connection metadata without credential resolution."""

from langboard_shared.core.db import DbSession
from langboard_shared.domain.models import AppConnection
from langboard_shared.helpers import InfraHelper
from sqlalchemy import select
from .GitHubManifest import GitHubManifestUnavailable, _board


def list_connections(service, actor, project_uid, after=None):
    _board(service, actor, project_uid)
    try:
        after_id = InfraHelper.convert_id(after) if after else 0
        statement = (
            select(AppConnection)
            .where(
                AppConnection.owner_id == actor.id,
                AppConnection.app_key == "github",
                AppConnection.state.in_(["pending", "connected"]),
                AppConnection.id > after_id,
            )
            .order_by(AppConnection.id)
            .limit(51)
        )
        with DbSession.use(readonly=False) as db:
            rows = [item[0] for item in db.exec(statement).all()]
        return {
            "items": [
                {"connection_uid": row.get_uid(), "app_id": row.external_account_id, "state": row.state}
                for row in rows[:50]
            ],
            "next_cursor": rows[49].get_uid() if len(rows) > 50 else None,
        }
    except Exception:
        raise GitHubManifestUnavailable() from None
