# ruff: noqa: F811
"""Independent wheel consumes native credential-scoped resource pages."""

from types import SimpleNamespace
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from langboard_sdk import AppResources, HttpTransport, NativeApiError
from langboard_shared.core.db import DbSession
from langboard_shared.core.routing import AppRouter
from langboard_shared.domain.services.factory.WorkflowStageService_app_test import board  # noqa: F401
from test_app_connection_resources import scope


@pytest.mark.asyncio
@pytest.mark.parametrize("board", ["sqlite-http"], indirect=True)
async def test_sdk_resource_paging_and_revocation_use_actual_native_http(board):
    connection, _, binding, rows, token = scope(board)
    app = FastAPI()
    app.include_router(AppRouter.api)
    calls = []
    with TestClient(app) as client:
        async def request(method, path, **kwargs):
            calls.append((method, path))
            return client.request(method, path, headers={"Authorization": f"Bearer {token}"}, **kwargs)

        resources = AppResources(HttpTransport(SimpleNamespace(request=request)))
        first = await resources.list(board[2].get_uid(), limit=2)
        assert first["connection_uid"] == connection.get_uid()
        assert first["binding_revision"] == binding.edit_revision()
        assert len(first["items"]) == 2
        assert first["items"][0]["resource_path"] == []
        assert first["items"][0]["health"] == "unknown"
        assert len(calls) == 1
        second = await resources.list(board[2].get_uid(), limit=2, after_uid=first["next_cursor"])
        assert [item["resource_uid"] for item in second["items"]] == [rows[-1].get_uid()]
        assert second["next_cursor"] is None
        with DbSession.atomic() as db:
            binding.granted_capabilities = []
            db.update(binding)
        with pytest.raises(NativeApiError) as denied:
            await resources.list(board[2].get_uid())
        assert denied.value.status_code == 403
        assert len(calls) == 3  # No retries, refresh or automatic page crawling.
