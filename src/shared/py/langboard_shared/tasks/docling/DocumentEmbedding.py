"""Official OpenAI-compatible embeddings for an explicitly configured internal AI binding."""

from json import dumps, loads
from typing import TYPE_CHECKING
from urllib.parse import urlsplit
from .DocumentRetrievalSettings import DocumentRetrievalSettings


if TYPE_CHECKING:
    from langchain_core.embeddings import Embeddings


SUPPORTED_PROVIDERS = frozenset({"OpenAI", "OpenAI Compatible", "LiteLLM"})


def snapshot_embedding_config(value: str, binding_uid: str, *, explicit: bool = False) -> dict | None:
    """Freeze non-secret upload settings; only an explicit action can bypass OFF."""
    config, settings = validate_embedding_config(value)
    if not settings.enabled and not explicit:
        return None
    if not isinstance(binding_uid, str) or not binding_uid:
        raise ValueError("An authoritative embedding binding is required")
    return {
        "binding_uid": binding_uid,
        "agent_llm": config["agent_llm"],
        "base_url": config["base_url"].strip().rstrip("/"),
        "model_name": config["model_name"].strip(),
        "retrieval": settings.model_dump(mode="json"),
    }


def resolve_embedding_snapshot(snapshot: dict, current_value: str) -> str:
    """Refresh secrets without replacing the snapshotted model or splitter."""
    current, _ = validate_embedding_config(current_value)
    if current["base_url"].strip().rstrip("/") != snapshot.get("base_url"):
        raise ValueError("Embedding endpoint changed; explicitly request processing again")
    if str(current.get("retrieval", {}).get("external_url") or "").rstrip("/") != str(
        snapshot.get("retrieval", {}).get("external_url") or ""
    ).rstrip("/"):
        raise ValueError("Vector endpoint changed; explicitly request processing again")
    resolved = {
        **snapshot,
        "api_key": current.get("api_key", ""),
        "retrieval": {
            **snapshot.get("retrieval", {}),
            **(
                {"external_api_key": current.get("retrieval", {}).get("external_api_key")}
                if current.get("retrieval", {}).get("external_api_key")
                else {}
            ),
        },
    }
    resolved.pop("binding_uid", None)
    validate_embedding_config(dumps(resolved))
    return dumps(resolved)


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


def validated_embeddings(embeddings: "Embeddings", dimensions: int) -> "Embeddings":
    """Apply the same finite-vector contract before any backend receives vectors."""
    from math import isfinite
    from langchain_core.embeddings import Embeddings

    if type(dimensions) is not int or not 1 <= dimensions <= 65536:
        raise ValueError("dimensions must be an integer from 1 to 65536")

    class ValidatedEmbeddings(Embeddings):
        """Reject invalid upstream vectors before the official transaction commits."""

        def embed_documents(self, texts: list[str]) -> list[list[float]]:
            vectors = embeddings.embed_documents(texts)
            if len(vectors) != len(texts):
                raise ValueError("Embedding provider returned an unexpected vector count")
            return [self._validate(vector) for vector in vectors]

        def embed_query(self, text: str) -> list[float]:
            return self._validate(embeddings.embed_query(text))

        @staticmethod
        def _validate(vector: list[float]) -> list[float]:
            if len(vector) != dimensions or any(
                type(value) not in (int, float) or not isfinite(value) for value in vector
            ):
                raise ValueError("Embedding vector dimension or numeric values do not match the configured model")
            return vector

    return ValidatedEmbeddings()
