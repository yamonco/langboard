"""Persisted native SCIM IDs work even when the IdP omits externalId."""

from types import SimpleNamespace
from unittest.mock import Mock
import pytest
from langboard_shared.core.db import DbSession
from langboard_shared.core.db.DbEngine import DbEngine
from langboard_shared.domain.models import EmployeeMembershipPolicy, ScimGroup
from langboard_shared.domain.services.factory.ScimProvisioningService import ScimProvisioningService
from langboard_shared.Env import Env
from sqlalchemy import create_engine


@pytest.fixture
def membership(monkeypatch):
    engine = create_engine("sqlite://")
    for model in (EmployeeMembershipPolicy, ScimGroup):
        model.__table__.create(engine)
    monkeypatch.setattr(DbEngine, "get_main_engine", lambda: engine)
    monkeypatch.setattr(type(Env), "SCIM_ISSUER", property(lambda _: "https://directory.example/"))
    monkeypatch.setattr(type(Env), "MCP_EMPLOYEE_GROUP_IDS", property(lambda _: []))
    with DbSession.use(readonly=False) as db:
        group = ScimGroup(display_name="Any IdP staff", external_id=None)
        other = ScimGroup(display_name="Customers", external_id="unrelated")
        db.insert(group)
        db.insert(other)
    repo = SimpleNamespace(
        user_identity_link=SimpleNamespace(
            get_by_user_provider=Mock(return_value=SimpleNamespace(issuer="https://directory.example"))
        ),
        scim_group_member=SimpleNamespace(
            get_groups_by_user=Mock(return_value=[(None, group)]), get_employee_users=Mock(return_value=[])
        ),
    )
    service = ScimProvisioningService(lambda _: None, lambda _: None, repo)
    yield service, group, other, repo
    engine.dispose()


def test_native_group_selection_survives_service_restart(membership):
    service, group, _, repo = membership
    user = SimpleNamespace(deleted_at=None, activated_at=True)
    assert service.is_employee(user) is None
    saved = service.save_employee_membership_settings([group.get_uid(), group.get_uid()])
    assert saved["group_uids"] == [group.get_uid()]
    restarted = ScimProvisioningService(lambda _: None, lambda _: None, repo)
    assert restarted.is_employee(user) is True
    restarted.list_employees()
    assert repo.scim_group_member.get_employee_users.call_args.kwargs["group_ids"] == [group.id]


def test_unselected_removed_and_empty_membership_fail_closed(membership):
    service, group, other, repo = membership
    user = SimpleNamespace(deleted_at=None, activated_at=True)
    service.save_employee_membership_settings([other.get_uid()])
    assert service.is_employee(user) is False
    service.save_employee_membership_settings([group.get_uid()])
    repo.scim_group_member.get_groups_by_user.return_value = []
    assert service.is_employee(user) is False
    service.save_employee_membership_settings([])
    assert service.is_employee(user) is False


def test_authority_change_never_reuses_old_employee_selection(membership, monkeypatch):
    service, group, _, repo = membership
    service.save_employee_membership_settings([group.get_uid()])
    monkeypatch.setattr(type(Env), "SCIM_ISSUER", property(lambda _: "https://new.example"))
    repo.user_identity_link.get_by_user_provider.return_value.issuer = "https://new.example"
    assert service.is_employee(SimpleNamespace(deleted_at=None, activated_at=True)) is False
    assert service.list_employees()["items"] == []
    repo.scim_group_member.get_employee_users.assert_not_called()


def test_unknown_group_cannot_grant_access(membership):
    service, _, _, _ = membership
    with pytest.raises(ValueError):
        service.save_employee_membership_settings(["not-a-synchronized-group"])
    assert service.get_employee_membership_settings()["configured"] is False


def test_avatar_projection_uses_verified_identity_and_bounded_reads(membership, monkeypatch):
    from langboard_shared.core.types import SafeDateTime
    from langboard_shared.domain.models import IdentityProvider, ScimGroupMember, User, UserIdentityLink
    from sqlalchemy import event

    service, group, _, _ = membership
    engine = DbEngine.get_main_engine()
    for model in (User, UserIdentityLink, ScimGroupMember):
        model.__table__.create(engine)
    with DbSession.use(readonly=False) as db:
        staff = User(
            firstname="Staff",
            lastname="Test",
            email="unrelated@customer.example",
            password="fixture",
            activated_at=SafeDateTime.now(),
        )
        customer = User(
            firstname="Customer",
            lastname="Test",
            email="looks-internal@staff.example",
            password="fixture",
            activated_at=SafeDateTime.now(),
        )
        db.insert(staff)
        db.insert(customer)
        db.insert(
            UserIdentityLink(
                user_id=staff.id,
                provider=IdentityProvider.Scim,
                issuer="https://directory.example/",
                external_id="staff",
            )
        )
        db.insert(ScimGroupMember(user_id=staff.id, group_id=group.id))
    service.save_employee_membership_settings([group.get_uid()])
    reads = []

    def record(connection, cursor, statement, params, context, executemany):
        if statement.lstrip().upper().startswith("SELECT"):
            reads.append(statement)

    event.listen(engine, "before_cursor_execute", record)
    result = service.classify_members([staff.id, customer.id])
    event.remove(engine, "before_cursor_execute", record)
    assert result == {staff.get_uid(): "internal", customer.get_uid(): "external"}
    assert len(reads) == 4
    service.save_employee_membership_settings([])
    assert service.classify_members([staff.id])[staff.get_uid()] == "external"
