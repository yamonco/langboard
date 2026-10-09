"""Board-owned App management through existing native REST contracts."""

import re
from dataclasses import asdict, dataclass
from typing import Literal
from .rest import ApiTransport
from .workflow import WorkflowStage


@dataclass(frozen=True)
class GlitchTipProject:
    organization: str
    project_slug: str
    expected_resource_revision: int | None = None


@dataclass(frozen=True)
class DokployResource:
    resource_type: Literal["project", "environment", "application", "compose"]
    external_id: str
    external_project_id: str | None = None
    environment_id: str | None = None
    expected_resource_revision: int | None = None


def _segment(value: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", value):
        raise ValueError("A native identifier or app key is required")
    return value


def _revision(value: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{64}", value):
        raise ValueError("A current native revision is required")
    return value


def _secret_reference(value: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"secret://ref/[A-Za-z0-9]{1,11}", value):
        raise ValueError("Use a native secret reference, never a credential value")
    return value


class AppManager:
    """Inspect Apps and manage reviewed board bindings; never registers provider code."""

    def __init__(self, transport: ApiTransport, project_uid: str):
        self.transport = transport
        self.path = f"/board/{_segment(project_uid)}/settings/apps"

    async def catalog(self) -> dict:
        return await self.transport.request("GET", self.path)

    async def workflow(self, app_key: str) -> dict:
        return await self.transport.request("GET", f"{self.path}/{_segment(app_key)}/workflow")

    async def prepare_workflow(self, app_key: str) -> dict:
        return await self.transport.request("POST", f"{self.path}/{_segment(app_key)}/workflow")

    async def save_workflow(
        self,
        app_key: str,
        binding_uid: str,
        expected_revision: str,
        mapping: dict[WorkflowStage, str] | None,
        *,
        enable_transitions: bool = False,
    ) -> dict:
        if type(enable_transitions) is not bool:
            raise ValueError("Transition enablement must be explicit")
        values = (
            None if mapping is None else {WorkflowStage(stage).value: _segment(uid) for stage, uid in mapping.items()}
        )
        return await self.transport.request(
            "PUT",
            f"{self.path}/{_segment(app_key)}/workflow",
            json={
                "binding_uid": _segment(binding_uid),
                "expected_revision": _revision(expected_revision),
                "workflow_mapping": values,
                "enable_transitions": enable_transitions,
            },
        )

    async def disable(self, app_key: str, binding_uid: str, expected_revision: str) -> dict:
        return await self.transport.request(
            "POST",
            f"{self.path}/{_segment(app_key)}/disable",
            json={
                "binding_uid": _segment(binding_uid),
                "expected_revision": _revision(expected_revision),
            },
        )

    def connections(
        self, app_key: str, *, selection_collection: Literal["projects", "selected"]
    ) -> "ConnectionManager":
        return ConnectionManager(self.transport, f"{self.path}/{_segment(app_key)}", selection_collection)


class ConnectionManager:
    """Native instance onboarding for adapters exposing connection/selection endpoints.

    GlitchTip uses projects; Dokploy uses selected. GitHub's installation OAuth
    and repository delta protocol are different and are not implemented here.
    Selection fields follow the adapter's server schema, not a new SDK policy.
    """

    def __init__(self, transport: ApiTransport, path: str, selection_collection: Literal["projects", "selected"]):
        if selection_collection not in {"projects", "selected"}:
            raise ValueError("A native selection collection is required")
        self.transport, self.path, self.collection = transport, path, selection_collection

    async def list(self, *, after: str | None = None) -> dict:
        return await self.transport.request(
            "GET", f"{self.path}/connections", params={"after": after} if after else None
        )

    async def request_secret_input(self) -> dict:
        return await self.transport.request("POST", f"{self.path}/secret-input")

    async def secret_input_status(self, input_uid: str) -> dict:
        return await self.transport.request("GET", f"{self.path}/secret-input/{_segment(input_uid)}")

    async def create(self, instance_url: str, credential_reference: str) -> dict:
        return await self.transport.request(
            "POST",
            f"{self.path}/connections",
            json={
                "instance_url": instance_url,
                "credential_reference": _secret_reference(credential_reference),
            },
        )

    async def discover(self, connection_uid: str, **filters: str) -> dict:
        return await self.transport.request(
            "GET", f"{self.path}/connections/{_segment(connection_uid)}/resources", params=filters or None
        )

    async def selected(self, connection_uid: str, *, after: str | None = None) -> dict:
        return await self.transport.request(
            "GET",
            f"{self.path}/connections/{_segment(connection_uid)}/{self.collection}",
            params={"after": after} if after else None,
        )

    async def select(
        self, connection_uid: str, expected_revision: str, selection: GlitchTipProject | DokployResource
    ) -> dict:
        expected_type = GlitchTipProject if self.collection == "projects" else DokployResource
        if not isinstance(selection, expected_type):
            raise ValueError("Selection must match the native adapter contract")
        fields = {key: value for key, value in asdict(selection).items() if value is not None}
        return await self.transport.request(
            "POST",
            f"{self.path}/connections/{_segment(connection_uid)}/{self.collection}",
            json={**fields, "expected_revision": _revision(expected_revision)},
        )

    async def remove(self, connection_uid: str, resource_uid: str, expected_revision: int) -> dict:
        if type(expected_revision) is not int or expected_revision < 0:
            raise ValueError("A current resource access revision is required")
        return await self.transport.request(
            "POST",
            f"{self.path}/connections/{_segment(connection_uid)}/{self.collection}/{_segment(resource_uid)}/remove",
            json={"expected_revision": expected_revision},
        )

    async def disconnect(self, connection_uid: str, expected_revision: str) -> dict:
        return await self.transport.request(
            "POST",
            f"{self.path}/connections/{_segment(connection_uid)}/disconnect",
            json={"expected_revision": _revision(expected_revision)},
        )
