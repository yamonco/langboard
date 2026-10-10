"""Native provider revisions fence account ownership and organization changes."""

import pytest
from langboard.apps.DokployConnection import _revision as dokploy_revision
from langboard.apps.GitHubInstallation import connection_revision as github_revision
from langboard.apps.GlitchTipConnection import _revision as glitchtip_revision
from langboard_shared.core.types import SnowflakeID
from langboard_shared.domain.models import AppConnection


@pytest.fixture(params=[("github", github_revision), ("glitchtip", glitchtip_revision), ("dokploy", dokploy_revision)])
def provider(request):
    app_key, revision = request.param
    connection = AppConnection(
        id=SnowflakeID(1),
        owner_id=SnowflakeID(2),
        app_key=app_key,
        ownership="personal",
        organization_id=None,
        instance_url="https://provider.example.invalid",
        credential_reference="secret://ref/fixture",
        state="connected",
        external_account_id="42",
    )
    return connection, revision


@pytest.mark.parametrize("ownership, organization_id", [("personal", None), ("organization", SnowflakeID(3))])
def test_unchanged_native_connection_revision_is_stable(provider, ownership, organization_id):
    connection, revision = provider
    connection.ownership = ownership
    connection.organization_id = organization_id
    assert revision(connection) == revision(connection)


def test_native_connection_revision_changes_when_ownership_changes(provider):
    connection, revision = provider
    original = revision(connection)
    # Isolate ownership to verify that it participates independently in the fence.
    connection.ownership = "organization"
    assert revision(connection) != original
    connection.ownership = "personal"
    assert revision(connection) == original


def test_native_connection_revision_changes_when_organization_changes(provider):
    connection, revision = provider
    original = revision(connection)
    connection.ownership = "organization"
    connection.organization_id = SnowflakeID(3)
    first_organization = revision(connection)
    assert first_organization != original
    connection.organization_id = SnowflakeID(4)
    assert revision(connection) != first_organization
    connection.organization_id = SnowflakeID(3)
    assert revision(connection) == first_organization
    connection.organization_id = None
    assert revision(connection) != first_organization
