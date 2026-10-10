# ruff: noqa: F811
"""Independent SDK wheel invokes the actual host execution authority/request routes."""

from types import SimpleNamespace
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from langboard.routes.settings import AppExecutionAuthorityApi  # noqa: F401
from langboard_sdk import AppExecution, HttpTransport, NativeApiError
from langboard_shared.core.db import DbSession
from langboard_shared.core.routing import AppRouter
from langboard_shared.domain.services.factory.WorkflowStageService_app_test import board  # noqa: F401
from test_app_execution_requests import prepare


@pytest.mark.asyncio
@pytest.mark.parametrize("board", ["sqlite-http"], indirect=True)
async def test_sdk_native_authority_request_duplicate_and_revocation(board):
    _, _, binding, _, card, token = prepare(board)
    app = FastAPI()
    app.include_router(AppRouter.api)
    calls = []
    with TestClient(app) as client:

        async def request(method, path, **kwargs):
            calls.append((method, path))
            return client.request(method, path, headers={"Authorization": f"Bearer {token}"}, **kwargs)

        execution = AppExecution(HttpTransport(SimpleNamespace(request=request)))
        args = board[2].get_uid(), card.get_uid()
        authority = await execution.authority(*args, generation=3)
        assert authority["state"] == "eligible" and authority["started"] is False
        assert authority["resource_revisions"]
        first = await execution.request(*args, generation=3)
        second = await execution.request(*args, generation=3)
        assert first["state"] == "requested" and first["started"] is False
        assert first["changed"] is True and second["changed"] is False
        assert first["request_uid"] == second["request_uid"]
        with DbSession.atomic() as db:
            binding.granted_capabilities = ["resources.read"]
            db.update(binding)
        with pytest.raises(NativeApiError) as denied:
            await execution.request(*args, generation=3)
        assert denied.value.status_code == 403
        assert len(calls) == 4
