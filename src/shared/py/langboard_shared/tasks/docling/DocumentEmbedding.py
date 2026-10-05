"""Official OpenAI-compatible embeddings for an explicitly configured internal AI binding."""

from json import loads
from typing import TYPE_CHECKING
from urllib.parse import urlsplit
from .DocumentRetrievalSettings import DocumentRetrievalSettings


if TYPE_CHECKING:
    from langchain_core.embeddings import Embeddings


SUPPORTED_PROVIDERS = frozenset({"OpenAI", "OpenAI Compatible", "LiteLLM"})


def validate_embedding_config(value: str) -> tuple[dict, DocumentRetrievalSettings]:
    config = loads(value)
    if not isinstance(config, dict) or config.get("agent_llm") not in SUPPORTED_PROVIDERS:
        raise ValueError("Select an OpenAI-compatible embedding provider")
    if not isinstance(config.get("model_name"), str) or not config["model_name"].strip():
        raise ValueError("An embedding model is required")
    base_url = config.get("base_url")
    if not isinstance(base_url, str):
        raise ValueError("An explicit embedding endpoint is required")
    parsed = urlsplit(base_url)
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("Invalid embedding endpoint")
    if not isinstance(config.get("api_key", ""), str):
        raise ValueError("Invalid embedding credential")
    return config, DocumentRetrievalSettings.model_validate(config.get("retrieval", {}))


def create_document_embeddings(value: str, allowed_base_urls: set[str]) -> "Embeddings":
    """Construction never sends a document, probes a model or starts indexing.

    Resolve deployment-approved endpoints before the official client can send
    text. Explicit credentials prevent ambient OpenAI environment fallback.
    """
    from langchain_openai import OpenAIEmbeddings

    config, settings = validate_embedding_config(value)
    base_url = config["base_url"].strip().rstrip("/")
    if base_url not in {url.strip().rstrip("/") for url in allowed_base_urls}:
        raise ValueError("Embedding endpoint must be approved in MODEL_PROVIDER_ALLOWED_BASE_URLS")
    return OpenAIEmbeddings(
        model=config["model_name"].strip(),
        base_url=base_url,
        api_key=config.get("api_key") or "not-required",
        check_embedding_ctx_length=False,
        chunk_size=32,
        max_retries=1,
        request_timeout=settings.timeout_seconds,
    )
