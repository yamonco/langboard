"""Provider-specific API adapters; common management and host authority stay shared."""

from .management import ConnectionManager, _revision, _segment
from .rest import ApiTransport


def _access_revision(value: int) -> int:
    if type(value) is not int or value < 0:
        raise ValueError("A current resource access revision is required")
    return value


class GlitchTipManager(ConnectionManager):
    def __init__(self, transport: ApiTransport, project_uid: str):
        super().__init__(transport, f"/board/{_segment(project_uid)}/settings/apps/glitchtip", "projects")

    async def enable_read(self, connection_uid: str, connection_revision: str, binding_revision: str) -> dict:
        """Explicitly authorize metadata/signals reads, never workflow transitions."""
        return await self.transport.request(
            "POST",
            f"{self.path}/connections/{_segment(connection_uid)}/read-access",
            json={
                "expected_connection_revision": _revision(connection_revision),
                "expected_binding_revision": _revision(binding_revision),
            },
        )

    async def refresh_issues(
        self,
        connection_uid: str,
        resource_uid: str,
        connection_revision: str,
        access_revision: int,
        *,
        cursor: str | None = None,
    ) -> dict:
        """Persist one bounded observation page; no automatic cursor traversal."""
        fields = {
            "expected_connection_revision": _revision(connection_revision),
            "expected_access_revision": _access_revision(access_revision),
        }
        if cursor is not None:
            fields["cursor"] = cursor
        return await self.transport.request(
            "POST",
            f"{self.path}/connections/{_segment(connection_uid)}/projects/{_segment(resource_uid)}/issues/refresh",
            json=fields,
        )


class DokployManager(ConnectionManager):
    def __init__(self, transport: ApiTransport, project_uid: str):
        super().__init__(transport, f"/board/{_segment(project_uid)}/settings/apps/dokploy", "selected")

    async def enable_read(self, connection_uid: str, connection_revision: str, binding_revision: str) -> dict:
        """Explicit metadata/deployment read consent, not deploy or workflow authority."""
        return await self.transport.request(
            "POST",
            f"{self.path}/connections/{_segment(connection_uid)}/enable-read",
            json={
                "expected_revision": _revision(connection_revision),
                "expected_binding_revision": _revision(binding_revision),
            },
        )

    async def refresh_deployments(
        self, connection_uid: str, resource_uid: str, connection_revision: str, access_revision: int
    ) -> dict:
        return await self.transport.request(
            "POST",
            f"{self.path}/connections/{_segment(connection_uid)}/selected/{_segment(resource_uid)}/refresh",
            json={
                "expected_revision": _revision(connection_revision),
                "expected_access_revision": _access_revision(access_revision),
            },
        )

    async def webhook_health(self, connection_uid: str) -> dict:
        return await self.transport.request("GET", f"{self.path}/connections/{_segment(connection_uid)}/webhook-health")

    async def request_webhook_secret_input(self) -> dict:
        return await self.transport.request("POST", f"{self.path}/webhook-secret-input")

    async def configure_webhook(
        self,
        connection_uid: str,
        connection_revision: str,
        binding_revision: str,
        config_revision: int,
        credential_reference: str,
        *,
        notification_id: str | None = None,
    ) -> dict:
        from .management import _secret_reference

        fields = self._webhook_revisions(connection_revision, binding_revision, config_revision)
        fields["credential_reference"] = _secret_reference(credential_reference)
        if notification_id is not None:
            fields["notification_id"] = notification_id
        return await self.transport.request(
            "POST", f"{self.path}/connections/{_segment(connection_uid)}/webhook-config", json=fields
        )

    async def verify_webhook(
        self,
        connection_uid: str,
        connection_revision: str,
        binding_revision: str,
        config_revision: int,
        callback_url: str,
    ) -> dict:
        if config_revision < 1:
            raise ValueError("An existing webhook config revision is required")
        fields = self._webhook_revisions(connection_revision, binding_revision, config_revision)
        fields["callback_url"] = callback_url
        return await self.transport.request(
            "POST", f"{self.path}/connections/{_segment(connection_uid)}/webhook-verify", json=fields
        )

    async def disable_webhook(
        self, connection_uid: str, connection_revision: str, binding_revision: str, config_revision: int
    ) -> dict:
        return await self.transport.request(
            "POST",
            f"{self.path}/connections/{_segment(connection_uid)}/webhook-disable",
            json=self._webhook_revisions(connection_revision, binding_revision, config_revision),
        )

    @staticmethod
    def _webhook_revisions(connection_revision: str, binding_revision: str, config_revision: int) -> dict:
        return {
            "expected_revision": _revision(connection_revision),
            "expected_binding_revision": _revision(binding_revision),
            "expected_config_revision": _access_revision(config_revision),
        }
