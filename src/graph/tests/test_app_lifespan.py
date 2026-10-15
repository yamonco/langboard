"""Exercise the production Graph app factory and checkpoint shutdown lifecycle."""

from importlib import import_module
import pytest
import sentry_sdk
from fastapi.testclient import TestClient
from langboard_shared.FastAPIAppConfig import FastAPIAppConfig
from sentry_sdk.integrations.fastapi import FastApiIntegration
from sentry_sdk.integrations.starlette import StarletteIntegration
from langboard_graph.core.graph import checkpoint


@pytest.fixture
def graph_app(tmp_path, monkeypatch):
    module = import_module("langboard_graph.App")
    config_file = tmp_path / "graph_config.json"
    FastAPIAppConfig(config_file).create(host="127.0.0.1", port=5020)
    monkeypatch.setattr(module, "APP_CONFIG_FILE", config_file)
    return module.App().create()


class CheckpointPool:
    def __init__(self):
        self.closed = 0

    async def close(self):
        self.closed += 1


@pytest.mark.asyncio
@pytest.mark.parametrize("exceptional_exit", [False, True])
async def test_actual_app_lifespan_closes_both_checkpoint_pools(graph_app, monkeypatch, exceptional_exit):
    pools = [CheckpointPool(), CheckpointPool()]
    monkeypatch.setattr(checkpoint, "_checkpoint_pool", pools[0])
    monkeypatch.setattr(checkpoint, "_thread_lock_pool", pools[1])
    monkeypatch.setattr(checkpoint, "_checkpoint_setup_done", True)

    async def run_lifespan():
        async with graph_app.router.lifespan_context(graph_app):
            assert [pool.closed for pool in pools] == [0, 0]
            if exceptional_exit:
                raise RuntimeError("test-only lifespan exit")

    if exceptional_exit:
        with pytest.raises(RuntimeError, match="test-only lifespan exit"):
            await run_lifespan()
    else:
        await run_lifespan()

    assert [pool.closed for pool in pools] == [1, 1]
    assert checkpoint._checkpoint_pool is None
    assert checkpoint._thread_lock_pool is None
    assert checkpoint._checkpoint_setup_done is False


def test_actual_app_boots_and_serves_health(graph_app):
    with TestClient(graph_app) as client:
        response = client.get("/health")
        assert response.status_code == 200
        assert response.json() == {"status": "ok", "runtime": "graph"}


def test_health_survives_repeated_sentry_instrumentation(graph_app):
    # FastAPI >=0.137 resolves sync handlers per request. Old Sentry releases
    # accumulated wrappers until ordinary health probes exhausted recursion.
    # No DSN means no telemetry leaves this test; the real integrations run.
    with sentry_sdk.init(
        dsn=None,
        default_integrations=False,
        integrations=[StarletteIntegration(), FastApiIntegration()],
    ):
        assert sentry_sdk.get_client().get_integration(FastApiIntegration) is not None
        with TestClient(graph_app) as client:
            for request_number in range(1200):
                response = client.get("/health")
                assert response.status_code == 200, request_number
                assert response.json() == {"status": "ok", "runtime": "graph"}
