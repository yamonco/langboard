from unittest.mock import AsyncMock
import anyio
import pytest
from langboard.mcp_integration.OAuth import LangboardOIDCProxy


def provider(store):
    instance = object.__new__(LangboardOIDCProxy)
    instance._client_storage = store
    return instance


@pytest.mark.parametrize("phase", ["put", "get", "delete"])
async def test_io_failure_is_safe_and_recovery_uses_same_provider(phase):
    store = AsyncMock()
    store.get.side_effect = lambda key, **kwargs: {"probe": key}
    getattr(store, phase).side_effect = OSError(5, "credential-secret /private/storage")
    instance = provider(store)
    result = await instance.storage_readiness()
    assert result == {"component": "oauth_storage", "status": "not_ready", "reason": "storage_io_error"}
    getattr(store, phase).side_effect = None
    store.get.side_effect = lambda key, **kwargs: {"probe": key}
    assert await instance.storage_readiness() == {"component": "oauth_storage", "status": "ready"}


async def test_mismatch_and_cleanup():
    store = AsyncMock()
    store.get.return_value = None
    result = await provider(store).storage_readiness()
    assert result["reason"] == "round_trip_mismatch"
    store.delete.assert_awaited_once()


async def test_timeout_includes_waiting_for_probe_lock():
    instance = provider(AsyncMock())
    instance._readiness_lock = anyio.Lock()
    acquired = anyio.Event()
    release = anyio.Event()

    async def hold_lock():
        async with instance._readiness_lock:
            acquired.set()
            await release.wait()

    async with anyio.create_task_group() as tasks:
        tasks.start_soon(hold_lock)
        await acquired.wait()
        result = await instance.storage_readiness(timeout=0.01)
        release.set()
    assert result["reason"] == "storage_timeout"
    instance._client_storage.put.assert_not_awaited()


async def test_probe_preserves_unrelated_credentials():
    from key_value.aio.stores.memory import MemoryStore

    store = MemoryStore()
    await store.put("client", {"value": "unchanged"}, collection="clients")
    instance = provider(store)
    assert (await instance.storage_readiness())["status"] == "ready"
    assert await store.get("client", collection="clients") == {"value": "unchanged"}
    assert (await instance.storage_readiness())["status"] == "ready"
