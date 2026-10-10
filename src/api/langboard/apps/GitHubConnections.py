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


def connection_health(service, actor, project_uid, connection_uid, after=None):
    """Board-scoped stored evidence, not a new GitHub API verification."""
    import re
    from langboard_shared.domain.models import AppResourceBinding, BoardAppBinding
    from sqlalchemy import and_, case, func, or_

    board = _board(service, actor, project_uid)
    with DbSession.use(readonly=False) as db:
        connection = db.exec(
            select(AppConnection).where(
                AppConnection.id == InfraHelper.convert_id(connection_uid),
                AppConnection.owner_id == actor.id,
                AppConnection.app_key == "github",
            )
        ).first()
        if connection is None:
            raise GitHubManifestUnavailable()
        connection = connection[0]
        installation = AppResourceBinding.resource_path[0]["id"].as_string()
        account = AppResourceBinding.resource_path[1]["id"].as_string()
        statement = (
            select(
                installation,
                account,
                func.count(),
                func.sum(
                    case(
                        (and_(AppResourceBinding.access_state == "granted", AppResourceBinding.health == "healthy"), 1),
                        else_=0,
                    )
                ),
                func.sum(case((AppResourceBinding.health == "degraded", 1), else_=0)),
                func.sum(case((AppResourceBinding.health == "unavailable", 1), else_=0)),
            )
            .join(BoardAppBinding, BoardAppBinding.id == AppResourceBinding.board_binding_id)
            .where(
                BoardAppBinding.project_id == board.id,
                BoardAppBinding.app_key == "github",
                AppResourceBinding.connection_id == connection.id,
                AppResourceBinding.resource_type == "repository",
                AppResourceBinding.is_selected == True,  # noqa: E712
                AppResourceBinding.resource_path[0]["type"].as_string() == "installation",
                AppResourceBinding.resource_path[1]["type"].as_string() == "account",
            )
        )
        if after is not None:
            if not isinstance(after, str) or not re.fullmatch(r"[1-9][0-9]{0,19}:[1-9][0-9]{0,19}", after):
                raise ValueError("Invalid installation cursor")
            install_after, account_after = after.split(":")
            statement = statement.where(
                or_(installation > install_after, and_(installation == install_after, account > account_after))
            )
        rows = db.exec(statement.group_by(installation, account).order_by(installation, account).limit(26)).all()
        items = []
        for install_id, account_id, total, healthy, degraded, unavailable in rows[:25]:
            items.append(
                {
                    "installation_id": install_id,
                    "account_id": account_id,
                    "selected_count": total,
                    "healthy_count": healthy,
                    "degraded_count": degraded,
                    "unavailable_count": unavailable,
                    "unverified_count": total - healthy - degraded - unavailable,
                }
            )
        return {
            "connection_uid": connection.get_uid(),
            "state": connection.state,
            "evidence": "stored",
            "items": items,
            "next_cursor": f"{rows[24][0]}:{rows[24][1]}" if len(rows) > 25 else None,
        }


def health_jobs(service, actor, project_uid, connection_uid, after=None):
    """Stored installation jobs relevant to this board; never reveal worker cursors or credentials."""
    from langboard_shared.domain.models import (
        AppResourceBinding,
        BoardAppBinding,
        GitHubHealthJob,
        GitHubLifecycleReceipt,
    )

    board = _board(service, actor, project_uid)
    import re

    try:
        if after is not None and (not isinstance(after, str) or not re.fullmatch(r"[0-9A-Za-z]{1,11}", after)):
            raise ValueError("Invalid job cursor")
        cursor = InfraHelper.convert_id(after) if after is not None else None
    except Exception:
        raise ValueError("Invalid job cursor") from None
    with DbSession.use(readonly=False) as db:
        connection = db.exec(
            select(AppConnection).where(
                AppConnection.id == InfraHelper.convert_id(connection_uid),
                AppConnection.owner_id == actor.id,
                AppConnection.app_key == "github",
            )
        ).first()
        if connection is None:
            raise GitHubManifestUnavailable()
        connection = connection[0]
        relevant = (
            select(AppResourceBinding.id)
            .join(BoardAppBinding, BoardAppBinding.id == AppResourceBinding.board_binding_id)
            .where(
                BoardAppBinding.project_id == board.id,
                BoardAppBinding.app_key == "github",
                AppResourceBinding.connection_id == connection.id,
                AppResourceBinding.resource_type == "repository",
                AppResourceBinding.is_selected == True,  # noqa: E712
                AppResourceBinding.resource_path[0]["id"].as_string() == GitHubLifecycleReceipt.installation_id,
                AppResourceBinding.resource_path[1]["id"].as_string() == GitHubLifecycleReceipt.account_id,
            )
            .exists()
        )
        statement = (
            select(GitHubHealthJob)
            .join(GitHubLifecycleReceipt, GitHubLifecycleReceipt.id == GitHubHealthJob.receipt_id)
            .where(GitHubLifecycleReceipt.connection_id == connection.id, relevant)
        )
        if cursor is not None:
            statement = statement.where(GitHubHealthJob.id < cursor)
        rows = [row[0] for row in db.exec(statement.order_by(GitHubHealthJob.id.desc()).limit(26)).all()]
        return {
            "items": [{"job_uid": row.get_uid(), "state": row.state} for row in rows[:25]],
            "next_cursor": rows[24].get_uid() if len(rows) > 25 else None,
        }
