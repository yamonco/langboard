import asyncio
import importlib
import json
import os
import httpx
import pytest


os.environ.setdefault("PROJECT_NAME", "langboard")
module = importlib.import_module("langboard.routes.settings.ModelProviderSettingsApi")


@pytest.fixture
def catalog(monkeypatch):
    requests = []
    responses = {"status": 200, "body": {"data": [{"id": "z"}, {"id": "a"}, {"id": "z"}, {"id": None}]}}

    async def target(url):
        return module.ResolvedWebhookTarget(
            url.replace("catalog.example", "93.184.216.34"), "catalog.example", "catalog.example"
        )

    def handler(request):
        requests.append(request)
        return httpx.Response(responses["status"], json=responses["body"])

    client = httpx.AsyncClient
    monkeypatch.setattr(
        module, "AsyncClient", lambda **kwargs: client(transport=httpx.MockTransport(handler), **kwargs)
    )
    monkeypatch.setattr(module, "ensure_public_webhook_url", target)
    monkeypatch.setattr(module.Env, "get_from_env", lambda *args: "")

    def invoke(url="https://catalog.example/v1"):
        response = asyncio.run(module.get_provider_models(module.ModelListForm(base_url=url, api_key="fixture-secret")))
        return response.status_code, json.loads(response.body)

    return invoke, requests, responses


def test_catalog_auth_and_sorted_deduplication(catalog):
    invoke, requests, _ = catalog
    assert invoke() == (200, {"models": ["a", "z"]})
    assert str(requests[0].url) == "https://93.184.216.34/v1/models"
    assert requests[0].headers["host"] == "catalog.example"
    assert requests[0].headers["authorization"] == "Bearer fixture-secret"
    assert requests[0].extensions["sni_hostname"] == "catalog.example"


@pytest.mark.parametrize(
    "url",
    [
        "http://catalog.example/v1",
        "https://user:password@catalog.example/v1",
        "https://catalog.example/v1?token=x",
        "https://catalog.example/v1#fragment",
    ],
)
def test_invalid_destinations_never_send_credentials(catalog, url):
    invoke, requests, _ = catalog
    assert invoke(url)[0] == 502
    assert requests == []


@pytest.mark.parametrize("status", [301, 401, 429, 500])
def test_upstream_failure_is_redacted(catalog, status):
    invoke, requests, responses = catalog
    responses.update(status=status, body={"secret": "fixture-secret"})
    code, body = invoke()
    assert code == 502
    assert body == {"models": [], "error": "model_provider_unavailable"}
    assert len(requests) == 1


def test_private_proxy_requires_exact_configured_base(catalog, monkeypatch):
    invoke, requests, _ = catalog
    monkeypatch.setattr(module.Env, "get_from_env", lambda *args: "http://litellm:4000/v1")
    assert invoke("http://litellm:4000/v1")[0] == 200
    assert str(requests[0].url) == "http://litellm:4000/v1/models"
    assert invoke("http://litellm:4000/other")[0] == 502
    assert len(requests) == 1


def test_public_policy_rejects_loopback(catalog, monkeypatch):
    from langboard_shared.tasks.webhooks.utils import ensure_public_webhook_url

    invoke, requests, _ = catalog
    monkeypatch.setattr(module, "ensure_public_webhook_url", ensure_public_webhook_url)
    assert invoke("https://127.0.0.1/v1")[0] == 502
    assert requests == []


def test_oversized_catalog_is_bounded(catalog):
    invoke, _, responses = catalog
    responses["body"] = {"data": [{"id": "z"}], "padding": "x" * (1024 * 1024)}
    assert invoke()[0] == 502


def test_invalid_catalog_is_not_silently_successful(catalog):
    invoke, _, responses = catalog
    responses["body"] = {"data": "not-a-list"}
    assert invoke()[0] == 502
