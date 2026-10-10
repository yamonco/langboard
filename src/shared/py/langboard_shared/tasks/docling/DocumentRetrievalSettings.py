"""Server bounds for optional document retrieval; changing settings never indexes files."""

from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, HttpUrl, SecretStr, model_validator
from .DocumentSplitter import DocumentSplitterSettings


class DocumentRetrievalSettings(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    enabled: bool = False
    store: Literal["sqlite", "qdrant"] = "sqlite"
    external_url: HttpUrl | None = None
    external_api_key: SecretStr | None = Field(default=None, exclude=True)
    dimensions: int = Field(default=1536, ge=1, le=65536)
    splitter: DocumentSplitterSettings = Field(default_factory=DocumentSplitterSettings)
    search_type: Literal["similarity", "mmr"] = "similarity"
    k: int = Field(default=5, ge=1, le=25)
    fetch_k: int = Field(default=20, ge=1, le=100)
    score_threshold: float | None = Field(default=None, ge=-1, le=1, allow_inf_nan=False)
    lambda_mult: float = Field(default=0.5, ge=0, le=1, allow_inf_nan=False)
    max_return_tokens: int = Field(default=4000, ge=128, le=16000)
    timeout_seconds: float = Field(default=10.0, ge=1, le=30, allow_inf_nan=False)

    @model_validator(mode="after")
    def validate_capabilities(self) -> "DocumentRetrievalSettings":
        if self.store == "sqlite":
            if self.external_url is not None or self.external_api_key is not None:
                raise ValueError("the built-in store has no external endpoint or credential")
            if self.search_type != "similarity":
                raise ValueError("the official SQLite store supports similarity search only")
        elif self.external_url is None:
            raise ValueError("Qdrant requires an explicit external endpoint")
        if self.external_url is not None and (self.external_url.username or self.external_url.password):
            raise ValueError("endpoint credentials must use the separate secret field")
        if self.external_url is not None and (self.external_url.query or self.external_url.fragment):
            raise ValueError("the store endpoint must not contain a query or fragment")
        if self.search_type == "mmr" and self.fetch_k < self.k:
            raise ValueError("fetch_k must be at least k for MMR")
        if self.search_type == "mmr" and self.score_threshold is not None:
            raise ValueError("MMR with a score threshold is not supported")
        return self
