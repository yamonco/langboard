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
        first = await execution.request(*args, generation=3, expected_authority_version=authority["authority_version"])
        second = await execution.request(*args, generation=3, expected_authority_version=authority["authority_version"])
        assert first["state"] == "requested" and first["started"] is False
        assert first["changed"] is True and second["changed"] is False
        assert first["request_uid"] == second["request_uid"]
        with DbSession.atomic() as db:
            binding.granted_capabilities = ["resources.read"]
            db.update(binding)
        with pytest.raises(NativeApiError) as denied:
            await execution.request(*args, generation=3, expected_authority_version=authority["authority_version"])
        assert denied.value.status_code == 403
        assert len(calls) == 4


@pytest.mark.asyncio
@pytest.mark.parametrize("board", ["sqlite-http"], indirect=True)
async def test_sdk_selection_compare_and_set_against_native_host(board):
    from langboard_shared.core.db import SqlBuilder
    from langboard_shared.domain.models import AppExecutionOutbox, AppExecutionRequest
    from langboard_shared.domain.services.CardAppResources import set_card_app_resources

    connection, _, _, resources, card, token = prepare(board)
    app = FastAPI()
    app.include_router(AppRouter.api)
    with TestClient(app) as client:

        async def request(method, path, **kwargs):
            return client.request(method, path, headers={"Authorization": f"Bearer {token}"}, **kwargs)

        execution = AppExecution(HttpTransport(SimpleNamespace(request=request)))
        args = board[2].get_uid(), card.get_uid()
        first = await execution.authority(*args, generation=3)
        set_card_app_resources(board[1], board[2].id, card.id, connection.id, [resources[1].get_uid()], 1)
        with pytest.raises(NativeApiError) as conflict:
            await execution.request(*args, generation=3, expected_authority_version=first["authority_version"])
        assert conflict.value.status_code == 409
        with DbSession.atomic() as db:
            assert not db.exec(SqlBuilder.select.table(AppExecutionRequest)).all()
            assert not db.exec(SqlBuilder.select.table(AppExecutionOutbox)).all()
        current = await execution.authority(*args, generation=3)
        receipt = await execution.request(*args, generation=3, expected_authority_version=current["authority_version"])
        assert receipt["authority"]["resource_uids"] == [resources[1].get_uid()]
        assert receipt["authority"]["authority_version"] == current["authority_version"]
        assert receipt["started"] is False
