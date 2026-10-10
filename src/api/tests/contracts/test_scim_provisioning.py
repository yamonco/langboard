import os


os.environ.setdefault("PROJECT_NAME", "langboard")

import pytest  # noqa: E402
from langboard_shared.domain.contracts.scim_provisioning import (  # noqa: E402
    ProvisionIntent,
    ScimOperation,
    ScimPatchOperation,
    ScimUserRequest,
    apply_deactivation,
    normalize_external_id,
    parse_patch_operations,
    plan_revocation,
)


class TestScimUserRequest:
    def test_valid_request(self):
        request = ScimUserRequest(external_id="ext-1", email="user@example.com", firstname="A", lastname="B")
        assert request.intent() is ProvisionIntent.REACTIVATE

    def test_inactive_maps_to_deactivate(self):
        request = ScimUserRequest(external_id="ext-1", email="user@example.com", firstname="A", lastname="B", active=False)
        assert request.intent() is ProvisionIntent.DEACTIVATE

    def test_rejects_blank_external_id(self):
        with pytest.raises(ValueError):
            ScimUserRequest(external_id="  ", email="user@example.com", firstname="A", lastname="B")

    def test_rejects_invalid_email(self):
        with pytest.raises(ValueError):
            ScimUserRequest(external_id="ext-1", email="not-an-email", firstname="A", lastname="B")


class TestNormalizeExternalId:
    def test_trims_and_stringifies(self):
        assert normalize_external_id("  42  ") == "42"
        assert normalize_external_id(42) == "42"
        assert normalize_external_id(None) == ""


class TestParsePatchOperations:
    def test_normalizes_known_ops(self):
        operations = parse_patch_operations(
            {"Operations": [{"op": "Replace", "path": "active", "value": False}, {"op": "add", "path": "emails", "value": []}]}
        )
        assert operations == (
            ScimPatchOperation(op=ScimOperation.REPLACE, path="active", value=False),
            ScimPatchOperation(op=ScimOperation.ADD, path="emails", value=[]),
        )

    def test_rejects_unknown_op(self):
        with pytest.raises(ValueError):
            parse_patch_operations({"Operations": [{"op": "explode", "path": "x"}]})

    def test_rejects_non_list(self):
        with pytest.raises(ValueError):
            parse_patch_operations({"Operations": "nope"})

    def test_rejects_missing_path(self):
        with pytest.raises(ValueError):
            parse_patch_operations({"Operations": [{"op": "replace", "path": " "}]})


class TestRevocation:
    def test_plan_deduplicates_sorted(self):
        plan = plan_revocation(
            user_uid="u1",
            organization_uid="org1",
            group_uids=("g2", "g1", "g2"),
            project_uids=("p1",),
        )
        assert plan.group_uids == ("g1", "g2")
        assert not plan.is_empty()

    def test_empty_plan(self):
        assert plan_revocation(user_uid="u1", organization_uid="org1").is_empty()

    def test_requires_identifiers(self):
        with pytest.raises(ValueError):
            plan_revocation(user_uid="", organization_uid="org1")

    def test_deactivation_removes_scoped_groups(self):
        plan = plan_revocation(user_uid="u1", organization_uid="org1", group_uids=("g1",))
        memberships = {"u1": ("g1", "g2"), "u2": ("g1",)}
        updated = apply_deactivation(plan, memberships)
        assert updated["u1"] == ("g2",)
        assert updated["u2"] == ("g1",)

    def test_deactivation_unscoped_removes_all(self):
        plan = plan_revocation(user_uid="u1", organization_uid="org1")
        updated = apply_deactivation(plan, {"u1": ("g1", "g2"), "u2": ("g3",)})
        assert "u1" not in updated
        assert updated["u2"] == ("g3",)
