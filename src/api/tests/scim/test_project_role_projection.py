import os
from types import SimpleNamespace
from typing import Any
import pytest


os.environ.setdefault("PROJECT_NAME", "langboard")
os.environ.setdefault("SCIM_ISSUER", "https://directory.example/scim")

from langboard.routes.scim.Form import ScimUserUpsertForm  # noqa: E402
from langboard.routes.scim.ScimApi import create_scim_user  # noqa: E402
from langboard_shared.core.exceptions import ScimProvisioningException  # noqa: E402
from langboard_shared.core.routing import ApiException  # noqa: E402
from langboard_shared.domain.models import Project, User  # noqa: E402
from langboard_shared.domain.services.factory.ScimProvisioningService import (  # noqa: E402
    ScimProvisioningService,
)
from langboard_shared.Env import Env  # noqa: E402
from langboard_shared.helpers import InfraHelper  # noqa: E402
from langboard_shared.security import Auth  # noqa: E402


class Role:
    def __init__(self, actions: list[str]) -> None:
        self.actions = actions

    def is_all_granted(self) -> bool:
        return "*" in self.actions


class RoleRepository:
    def __init__(self) -> None:
        self.roles: dict[tuple[int, int], Role] = {}

    def grant(self, *, actions: list[str], user_id: int, project_id: int) -> Role:
        role = Role(actions)
        self.roles[(project_id, user_id)] = role
        return role

    def grant_all(self, *, user_id: int, project_id: int) -> Role:
        return self.grant(actions=["*"], user_id=user_id, project_id=project_id)

    def get_one(self, *, user_id: int, project_id: int) -> Role | None:
        return self.roles.get((project_id, user_id))


class AssignedRepository:
    def __init__(self, users: list[Any], role_repository: RoleRepository) -> None:
        self.users = {user.id: user for user in users}
        self.role_repository = role_repository

    def get_all_by_project(self, _project: Any) -> list[tuple[Any, Any]]:
        return [(user, SimpleNamespace(user_id=user.id)) for user in self.users.values()]

    def ensure_assigned(self, _project: Any, user: Any) -> tuple[Any, bool]:
        created = user.id not in self.users
        self.users[user.id] = user
        return SimpleNamespace(user_id=user.id), created

    def delete_all_by_project_and_users(self, project: Any, users: list[Any]) -> None:
        for user in users:
            self.users.pop(user.id, None)
            self.role_repository.roles.pop((project.id, user.id), None)


class IdentityService:
    def __init__(self, managed_user_ids: set[int]) -> None:
        self.managed_user_ids = managed_user_ids
        self.external_users: dict[str, Any] = {}
        self.upserts: list[dict[str, Any]] = []

    def get_by_user_provider(self, user: Any, _provider: Any) -> Any | None:
        if user.id not in self.managed_user_ids:
            return None
        return SimpleNamespace(external_id=f"employee-{user.id}", issuer="https://directory.example/scim")

    def get_user_by_provider_external_id(
        self,
        _provider: Any,
        external_id: str,
        _issuer: str | None = None,
    ) -> Any | None:
        return self.external_users.get(external_id)

    def upsert_user_link(self, **kwargs: Any) -> Any:
        self.upserts.append(kwargs)
        return SimpleNamespace(**kwargs)


def make_service(repository: Any, identity: IdentityService, user_service: Any | None = None) -> ScimProvisioningService:
    services = {
        "identity_link": identity,
        "user": user_service or SimpleNamespace(),
    }
    return ScimProvisioningService(
        lambda service_type: services[service_type.name()],
        lambda name: services[name],
        repository,
    )


def test_external_id_does_not_auto_link_an_existing_email() -> None:
    existing = SimpleNamespace(id=7, email="person@example.com")
    identity = IdentityService(set())
    user_service = SimpleNamespace(get_by_email=lambda _email: (existing, None))
    service = make_service(SimpleNamespace(), identity, user_service)

    with pytest.raises(ScimProvisioningException.Conflict):
        service.create_or_upsert_user(
            {"externalId": "employee-7", "userName": "person@example.com"}
        )

    assert identity.upserts == []


def test_scim_api_explains_that_an_existing_account_needs_explicit_linking(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Provisioning:
        @staticmethod
        def create_or_upsert_user(_payload: dict[str, Any]) -> None:
            raise ScimProvisioningException.IdentityLinkRequired()

    monkeypatch.setattr(Auth, "ensure_scim_authorized", lambda _headers: None)

    with pytest.raises(ApiException.Conflict_409) as caught:
        create_scim_user(
            ScimUserUpsertForm(
                externalId="employee-7",
                userName="person@example.com",
            ),
            SimpleNamespace(headers={}),
            SimpleNamespace(scim_provisioning=Provisioning()),
        )

    assert caught.value.detail == {
        "code": "EX1005",
        "message": "An existing account with this email must be linked explicitly before SCIM provisioning.",
    }


def test_explicit_user_update_can_link_a_preexisting_account() -> None:
    user = SimpleNamespace(
        id=7,
        email="person@example.com",
        firstname="Pat",
        lastname="Lee",
        activated_at=object(),
    )
    identity = IdentityService(set())
    service = make_service(SimpleNamespace(), identity)

    service.apply_user_mutations(user, {"externalId": "employee-7"})

    assert identity.upserts[0]["user"] is user
    assert identity.upserts[0]["external_id"] == "employee-7"


def test_external_id_conflict_is_rejected_before_profile_mutation() -> None:
    user = SimpleNamespace(
        id=7,
        email="person@example.com",
        firstname="Pat",
        lastname="Lee",
        activated_at=object(),
    )
    other_user = SimpleNamespace(id=8)
    identity = IdentityService({user.id})
    identity.external_users["employee-8"] = other_user
    user_service = SimpleNamespace(
        update=lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("profile mutated"))
    )
    service = make_service(SimpleNamespace(), identity, user_service)

    with pytest.raises(ScimProvisioningException.Conflict):
        service.apply_user_mutations(
            user,
            {"externalId": "employee-8", "name": {"givenName": "Changed"}},
        )

    assert user.firstname == "Pat"


def test_project_role_groups_reconcile_membership_role_and_revocation() -> None:
    owner = SimpleNamespace(id=1, email="owner@example.com")
    employee = SimpleNamespace(id=2, email="employee@example.com")
    stale_employee = SimpleNamespace(id=3, email="stale@example.com")
    external = SimpleNamespace(id=4, email="guest@example.com")
    project = SimpleNamespace(id=10, owner_id=owner.id, get_uid=lambda: "project-a")
    groups = {
        "project-role:project-a:viewer": SimpleNamespace(id=101),
        "project-role:project-a:contributor": SimpleNamespace(id=102),
    }
    members = {
        101: [(SimpleNamespace(user_id=employee.id), employee)],
        102: [(SimpleNamespace(user_id=employee.id), employee)],
    }
    role_repository = RoleRepository()
    assigned_repository = AssignedRepository(
        [owner, employee, stale_employee, external], role_repository
    )
    relationship_calls: list[set[int]] = []
    repository = SimpleNamespace(
        scim_group=SimpleNamespace(get_by_external_id=lambda external_id: groups.get(external_id)),
        scim_group_member=SimpleNamespace(
            get_users_by_group=lambda group: members.get(group.id, [])
        ),
        project_assigned_user=assigned_repository,
        project_user_relationship=SimpleNamespace(
            ensure_project_relationships=lambda _project, user_ids: relationship_calls.append(set(user_ids))
        ),
        role=SimpleNamespace(project=role_repository),
    )
    service = make_service(repository, IdentityService({employee.id, stale_employee.id}))

    service._reconcile_project_entitlements(project)

    assert set(assigned_repository.users) == {owner.id, employee.id, external.id}
    assert role_repository.get_one(user_id=employee.id, project_id=project.id).actions == [
        "read",
        "card_write",
        "card_update",
    ]
    assert relationship_calls[-1] == {owner.id, employee.id, external.id}

    members[101] = []
    members[102] = []
    service._reconcile_project_entitlements(project)

    assert set(assigned_repository.users) == {owner.id, external.id}


def test_bound_group_rejects_a_user_without_current_scim_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = SimpleNamespace(id=10, owner_id=1, get_uid=lambda: "project-a")
    local_user = SimpleNamespace(id=4)
    identity = IdentityService(set())
    service = make_service(SimpleNamespace(), identity)

    def resolve(model: Any, identifier: Any, **_kwargs: Any) -> Any | None:
        if model is Project and identifier == "project-a":
            return project
        if model is User and identifier == local_user.id:
            return local_user
        return None

    monkeypatch.setattr(InfraHelper, "get_by_id_like", resolve)

    with pytest.raises(ScimProvisioningException.InvalidRequest):
        service._validate_project_role_members("project-role:project-a:viewer", [local_user.id])


def test_bound_group_fails_closed_without_a_configured_scim_issuer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = SimpleNamespace(id=10, owner_id=1, get_uid=lambda: "project-a")
    scim_user = SimpleNamespace(id=4)
    identity = IdentityService({scim_user.id})
    service = make_service(SimpleNamespace(), identity)

    def resolve(model: Any, identifier: Any, **_kwargs: Any) -> Any | None:
        if model is Project and identifier == "project-a":
            return project
        if model is User and identifier == scim_user.id:
            return scim_user
        return None

    monkeypatch.setattr(InfraHelper, "get_by_id_like", resolve)
    monkeypatch.setattr(type(Env), "SCIM_ISSUER", property(lambda _self: ""))

    with pytest.raises(ScimProvisioningException.InvalidRequest):
        service._validate_project_role_members("project-role:project-a:viewer", [scim_user.id])


def test_deactivation_removes_group_memberships_before_reconciling_access(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user = SimpleNamespace(id=2, activated_at=object())
    project = SimpleNamespace(id=10)
    calls: list[tuple[str, Any]] = []
    identity = IdentityService({user.id})
    user_service = SimpleNamespace(
        update=lambda target, form, **_kwargs: calls.append(("deactivate", (target, form)))
    )
    repository = SimpleNamespace(
        scim_group_member=SimpleNamespace(
            delete_all_by_user=lambda target: calls.append(("delete_memberships", target))
        )
    )
    service = make_service(repository, identity, user_service)
    monkeypatch.setattr(service, "_bound_projects_for_user", lambda _user: [project])
    monkeypatch.setattr(
        service,
        "_reconcile_project_entitlements",
        lambda target: calls.append(("reconcile", target)),
    )

    service.deactivate_user(user)

    assert [name for name, _ in calls] == ["deactivate", "delete_memberships", "reconcile"]


@pytest.mark.parametrize(
    "external_id",
    ["project-role:project-a", "project-role::viewer", "project-role:project-a:editor"],
)
def test_reserved_project_role_group_format_is_fail_closed(external_id: str) -> None:
    service = make_service(SimpleNamespace(), IdentityService(set()))

    with pytest.raises(ScimProvisioningException.InvalidRequest):
        service._parse_project_role_external_id(external_id)
