# ruff: noqa: F811
"""Current organization authority before provider IO and after metadata retrieval."""

import pytest
from langboard.apps import DokployConnection, GlitchTipConnection
from langboard_shared.core.db import DbSession, SqlBuilder
from langboard_shared.core.types import SafeDateTime
from langboard_shared.domain.models import AppConnection, Organization
from test_dokploy_connection import connect as dokploy_connect  # noqa: F401
from test_dokploy_connection import setup as dokploy_setup  # noqa: F401
from test_github_installation import board, secrets  # noqa: F401
from test_glitchtip_connection import connect as glitchtip_connect  # noqa: F401
from test_glitchtip_connection import setup as glitchtip_setup  # noqa: F401


@pytest.mark.parametrize("provider", ["dokploy", "glitchtip"])
@pytest.mark.parametrize("failure", [None, "foreign", "inactive", "suspended", "inflight"])
def test_metadata_requires_current_matching_organization(request, provider, failure, secrets):
    state = request.getfixturevalue(f"{provider}_setup")
    service, board, _, calls, external = state
    adapter, connect = (DokployConnection, dokploy_connect) if provider == "dokploy" else (GlitchTipConnection, glitchtip_connect)
    connection = connect(state)
    with DbSession.atomic() as db:
        organization = Organization(name="Metadata scope", slug="metadata-scope", owner_user_id=board[1].id)
        db.insert(organization)
        saved = db.exec(SqlBuilder.select.table(AppConnection)).first()
        saved.ownership, saved.organization_id = "organization", organization.id
        board[2].organization_id = organization.id
        if failure == "foreign":
            board[2].organization_id = None
        elif failure == "inactive":
            organization.is_active = False
        elif failure == "suspended":
            organization.suspended_at = SafeDateTime.now()
        for row in (organization, saved, board[2]):
            db.update(row)
    if failure == "inflight":
        def suspend():
            with DbSession.atomic() as db:
                organization.suspended_at = SafeDateTime.now()
                db.update(organization)
        external["after"] = suspend
    before = len(calls)
    if failure:
        unavailable = DokployConnection.DokployUnavailable if provider == "dokploy" else GlitchTipConnection.GlitchTipUnavailable
        with pytest.raises(unavailable):
            adapter.discover_resources(service, board[1], board[2].get_uid(), connection["connection_uid"])
        assert len(calls) - before == (1 if failure == "inflight" else 0)
    else:
        result = adapter.discover_resources(service, board[1], board[2].get_uid(), connection["connection_uid"])
        assert result["items"] and len(calls) == before + 1
