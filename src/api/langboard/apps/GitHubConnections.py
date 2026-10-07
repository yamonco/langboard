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


def inspect_app(service, actor, project_uid, connection_uid):
    import re
    import httpx
    from .GitHubInstallation import API, HEADERS, app_authentication, connection_revision

    try:
        connection, credential, token = app_authentication(service, actor, project_uid, connection_uid)
        revision = connection_revision(connection)
        with httpx.Client(timeout=15, follow_redirects=False) as client:
            response = client.get(API + "/app", headers={**HEADERS, "Authorization": "Bearer " + token})
        if response.status_code != 200:
            raise GitHubManifestUnavailable()
        data = response.json()
        if type(data.get("id")) is not int or data["id"] != credential["id"]:
            raise GitHubManifestUnavailable()
        slug = data.get("slug")
        if not isinstance(slug, str) or not re.fullmatch(r"[a-zA-Z0-9-]{1,100}", slug):
            raise GitHubManifestUnavailable()
        _board(service, actor, project_uid)
        with DbSession.use(readonly=False) as db:
            current = db.exec(select(AppConnection).where(AppConnection.id == connection.id)).first()
            if current is None or connection_revision(current[0]) != revision:
                raise GitHubManifestUnavailable()
        return {
            "connection_uid": connection.get_uid(),
            "app_id": data["id"],
            "slug": slug,
            "installation_url": f"https://github.com/apps/{slug}/installations/new",
        }
    except Exception:
        raise GitHubManifestUnavailable() from None
