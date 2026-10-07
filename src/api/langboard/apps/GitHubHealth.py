"""Bounded current-authority resource refresh for one verified lifecycle receipt."""

from langboard_shared.core.db import DbSession, SqlBuilder
from langboard_shared.domain.models import AppConnection, BoardAppBinding, GitHubLifecycleReceipt, User
from langboard_shared.helpers import InfraHelper
from .GitHubInstallation import connection_revision
from .GitHubManifest import GitHubManifestUnavailable
from .GitHubResources import refresh_resources


def refresh_receipt_resources(service, receipt_uid, project_uid, after=None):
    """One explicit worker page. Receipt provenance does not grant board authority."""
    with DbSession.use(readonly=False) as db:
        receipt = db.exec(
            SqlBuilder.select.table(GitHubLifecycleReceipt).where(
                GitHubLifecycleReceipt.id == InfraHelper.convert_id(receipt_uid),
            )
        ).first()
        if receipt is None or not receipt.invalidated or receipt.event == "ping":
            raise GitHubManifestUnavailable()
        connection = db.exec(
            SqlBuilder.select.table(AppConnection).where(AppConnection.id == receipt.connection_id)
        ).first()
        if (
            connection is None
            or connection.app_key != "github"
            or connection.state not in {"pending", "connected"}
            or connection.external_account_id != receipt.app_id
            or connection_revision(connection) != receipt.connection_revision
        ):
            raise GitHubManifestUnavailable()
        actor = db.exec(SqlBuilder.select.table(User).where(User.id == connection.owner_id)).first()
        if actor is None or actor.deleted_at is not None or actor.activated_at is None:
            raise GitHubManifestUnavailable()
        binding = db.exec(
            SqlBuilder.select.table(BoardAppBinding).where(
                BoardAppBinding.project_id == InfraHelper.convert_id(project_uid),
                BoardAppBinding.app_key == "github",
            )
        ).first()
        if binding is None:
            raise GitHubManifestUnavailable()
    return refresh_resources(
        service,
        actor,
        project_uid,
        connection.get_uid(),
        None,
        after,
        installation_scope=(receipt.installation_id, receipt.account_id),
        repository_scope=tuple(str(value) for value in (*receipt.added_repository_ids, *receipt.removed_repository_ids))
        if receipt.event == "installation_repositories"
        else None,
        expected_connection_revision=receipt.connection_revision,
        receipt_page=True,
    )
