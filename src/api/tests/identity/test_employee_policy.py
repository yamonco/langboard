"""Explicit employee policy never converts a login into directory permission."""

from importlib import import_module
from types import SimpleNamespace
from unittest.mock import Mock
import pytest
from langboard.mcp_tools.UserMcp import get_employee_status, list_employees
from langboard_shared.domain.services.factory import ScimProvisioningService


policy_module = import_module("langboard_shared.domain.services.factory.ScimProvisioningService")


def fixture(
    monkeypatch,
    *,
    groups=("employees",),
    issuer="https://directory.example",
    linked_issuer="https://directory.example",
    member=True,
):
    monkeypatch.setattr(policy_module, "Env", SimpleNamespace(MCP_EMPLOYEE_GROUP_IDS=list(groups), SCIM_ISSUER=issuer))
    identities = SimpleNamespace(get_by_user_provider=Mock(return_value=SimpleNamespace(issuer=linked_issuer)))
    repository = SimpleNamespace(
        user_identity_link=identities,
        scim_group_member=SimpleNamespace(
            get_groups_by_user=Mock(return_value=[(None, SimpleNamespace(external_id="employees"))] if member else []),
            get_employee_users=Mock(return_value=[]),
        )
    )
    service = ScimProvisioningService(lambda cls: identities, lambda name: None, repository)
    user = SimpleNamespace(id=1, activated_at=True, deleted_at=None, is_admin=False)
    return service, user, repository


@pytest.mark.parametrize("groups,issuer", [([], "https://directory.example"), (["employees"], "")])
def test_missing_policy_returns_unknown_without_reading_membership(monkeypatch, groups, issuer):
    service, user, repository = fixture(monkeypatch, groups=groups, issuer=issuer)
    assert service.is_employee(user) is None
    assert service.list_employees()["policy_status"] == "unknown"
    repository.scim_group_member.get_groups_by_user.assert_not_called()
    repository.scim_group_member.get_employee_users.assert_not_called()


@pytest.mark.parametrize("state", ["member", "removed", "other_issuer", "inactive", "deleted"])
def test_latest_scim_membership_and_identity_determine_classification(monkeypatch, state):
    service, user, repository = fixture(
        monkeypatch,
        member=state != "removed",
        linked_issuer="https://other.example" if state == "other_issuer" else "https://directory.example/",
    )
    if state == "inactive":
        user.activated_at = None
    if state == "deleted":
        user.deleted_at = True
    assert service.is_employee(user) is (state == "member")
    if state in ("member", "removed"):
        repository.scim_group_member.get_groups_by_user.assert_called_once_with(user, consistent=True)


def test_directory_denies_regular_authenticated_employee(monkeypatch):
    service, user, repository = fixture(monkeypatch)
    domain = SimpleNamespace(scim_provisioning=service)
    assert get_employee_status(user, domain)["is_employee"] is True
    with pytest.raises(PermissionError):
        list_employees(user, domain)
    repository.scim_group_member.get_employee_users.assert_not_called()


def test_admin_directory_is_bounded_and_omits_identity_and_email(monkeypatch):
    service, user, repository = fixture(monkeypatch)
    user.is_admin = True
    member = SimpleNamespace(
        username="person", firstname="First", lastname="Last", email="private@example", get_uid=lambda: "public-id"
    )
    repository.scim_group_member.get_employee_users.return_value = [member, member]
    result = list_employees(user, SimpleNamespace(scim_provisioning=service), page=2, limit=1)
    assert result["has_more"] is True
    assert result["items"] == [{"uid": "public-id", "username": "person", "firstname": "First", "lastname": "Last"}]
    repository.scim_group_member.get_employee_users.assert_called_once_with(
        ["employees"], "https://directory.example", offset=1, limit=2
    )
    with pytest.raises(ValueError):
        service.list_employees(page=0)
    with pytest.raises(ValueError):
        service.list_employees(limit=51)


def test_employee_query_filters_before_pagination_and_deduplicates_groups(monkeypatch):
    from contextlib import contextmanager
    from langboard_shared.domain.models import User
    from sqlalchemy import create_engine, text

    module = import_module("langboard_shared.infrastructure.repositories.factory.ScimGroupMemberRepository")
    engine = create_engine("sqlite://")
    with engine.begin() as connection:
        columns = ", ".join(
            f'"{column.name}" {"INTEGER" if column.name == "id" else "TEXT"}' for column in User.__table__.columns
        )
        connection.execute(text(f"CREATE TABLE user ({columns})"))
        connection.execute(text("CREATE TABLE user_identity_link (user_id INTEGER, provider TEXT, issuer TEXT)"))
        connection.execute(text("CREATE TABLE scim_group_member (user_id INTEGER, group_id INTEGER)"))
        connection.execute(text("CREATE TABLE scim_group (id INTEGER, external_id TEXT)"))
        connection.execute(text("INSERT INTO scim_group VALUES (1, 'employees'), (2, 'employees-two'), (3, 'guests')"))
        for uid, issuer, active, deleted, group in [
            (1, "https://directory.example", True, False, 1),
            (2, "https://other.example", True, False, 1),
            (3, "https://directory.example", False, False, 1),
            (4, "https://directory.example", True, True, 1),
            (5, "https://directory.example", True, False, 3),
            (6, "https://directory.example", True, False, 1),
        ]:
            connection.execute(
                text("INSERT INTO user (id, activated_at, deleted_at) VALUES (:id, :active, :deleted)"),
                {"id": uid, "active": "2026-10-04" if active else None, "deleted": "2026-10-04" if deleted else None},
            )
            connection.execute(
                text("INSERT INTO user_identity_link VALUES (:id, 'scim', :issuer)"), {"id": uid, "issuer": issuer}
            )
            connection.execute(text("INSERT INTO scim_group_member VALUES (:id, :group)"), {"id": uid, "group": group})
        connection.execute(text("INSERT INTO scim_group_member VALUES (1, 2)"))

    @contextmanager
    def session(**kwargs):
        assert kwargs == {"readonly": False}
        with engine.connect() as connection:
            yield SimpleNamespace(exec=connection.execute)

    monkeypatch.setattr(module.DbSession, "use", session)
    repository = module.ScimGroupMemberRepository.__new__(module.ScimGroupMemberRepository)
    assert [
        row.id
        for row in repository.get_employee_users(
            ["employees", "employees-two"], "https://directory.example", offset=0, limit=1
        )
    ] == [1]
    assert [
        row.id
        for row in repository.get_employee_users(
            ["employees", "employees-two"], "https://directory.example", offset=1, limit=1
        )
    ] == [6]
    assert repository.get_employee_users(["employees"], "https://missing.example", offset=0, limit=50) == []
    engine.dispose()
