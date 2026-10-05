import json
import httpx
import langchain_openai
import pytest
from langboard_shared.tasks.docling.DocumentEmbedding import create_document_embeddings, validate_embedding_config


def test_official_embeddings_use_only_explicit_binding_without_chat_overrides(monkeypatch):
    requests = []
    original = langchain_openai.OpenAIEmbeddings

    def handle(request):
        requests.append(request)
        body = json.loads(request.content)
        assert body["model"] == "fixture-embedding"
        assert body["input"] == ["한국어 문서", "日本語の資料"]
        assert "dimensions" not in body
        assert "system_prompt" not in body
        return httpx.Response(
            200,
            json={
                "object": "list",
                "model": "fixture-embedding",
                "data": [{"object": "embedding", "index": i, "embedding": [0.1, 0.2, 0.3]} for i in range(2)],
                "usage": {"prompt_tokens": 4, "total_tokens": 4},
            },
        )

    with httpx.Client(transport=httpx.MockTransport(handle)) as client:
        monkeypatch.setattr(
            langchain_openai, "OpenAIEmbeddings", lambda **kwargs: original(**kwargs, http_client=client)
        )
        monkeypatch.setenv("OPENAI_API_KEY", "ambient-secret-must-not-be-used")
        value = json.dumps(
            {
                "agent_llm": "OpenAI Compatible",
                "base_url": "https://fixture.invalid/v1",
                "model_name": "fixture-embedding",
                "system_prompt": "ignored",
                "retrieval": {"enabled": True},
            }
        )
        embedding = create_document_embeddings(value, {"https://fixture.invalid/v1"})
        assert not requests  # Configuration does not send documents or trigger a probe.
        assert embedding.embed_documents(["한국어 문서", "日本語の資料"]) == [[0.1, 0.2, 0.3]] * 2
    assert len(requests) == 1
    assert requests[0].url == "https://fixture.invalid/v1/embeddings"
    assert requests[0].headers["authorization"] == "Bearer not-required"


def test_binding_validation_rejects_invalid_settings_and_unapproved_destinations():
    valid = {"agent_llm": "OpenAI", "base_url": "https://api.openai.com/v1", "model_name": "text-embedding-3-small"}
    assert validate_embedding_config(json.dumps(valid))[1].enabled is False
    for patch in [
        {"agent_llm": "Anthropic"},
        {"model_name": ""},
        {"base_url": "file:///tmp/test"},
        {"base_url": "https://user:secret@example.com/v1"},
        {"api_key": 2},
        {"retrieval": {"enabled": "true"}},
        {"retrieval": {"timeout_seconds": 31}},
    ]:
        with pytest.raises(ValueError):
            validate_embedding_config(json.dumps({**valid, **patch}))
    with pytest.raises(ValueError, match="approved"):
        create_document_embeddings(json.dumps(valid), set())
