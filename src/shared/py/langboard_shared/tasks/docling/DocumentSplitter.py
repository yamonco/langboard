"""Validated RAG chunk settings backed by official LangChain splitters."""

from typing import TYPE_CHECKING, Any, Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator


if TYPE_CHECKING:
    from langchain_core.documents import Document


class DocumentSplitterSettings(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    type: Literal["recursive", "character", "markdown"] = "recursive"
    chunk_size: int = Field(default=1000, ge=64, le=8192)
    chunk_overlap: int = Field(default=150, ge=0, le=2048)
    length_unit: Literal["characters", "tokens"] = "characters"
    encoding: Literal["cl100k_base", "o200k_base"] = "cl100k_base"
    separators: list[str] = Field(
        default_factory=lambda: ["\n\n", "\n", "。", "．", ".", "，", "、", ",", " ", ""],
        min_length=1,
        max_length=16,
    )
    separator: str = Field(default="\n\n", max_length=32)
    keep_separator: Literal[False, "start", "end"] = "start"
    strip_whitespace: bool = True
    markdown_headers: list[int] = Field(default_factory=lambda: [1, 2, 3], min_length=1, max_length=6)
    strip_headers: bool = False

    @model_validator(mode="after")
    def validate_combinations(self) -> "DocumentSplitterSettings":
        if self.chunk_overlap >= self.chunk_size:
            raise ValueError("chunk_overlap must be smaller than chunk_size")
        if any(len(separator) > 32 for separator in self.separators):
            raise ValueError("separators must contain at most 32 characters each")
        if self.type != "character" and self.separators[-1] != "":
            raise ValueError("recursive splitting requires an empty final separator")
        if len(set(self.markdown_headers)) != len(self.markdown_headers) or any(
            type(level) is not int or not 1 <= level <= 6 for level in self.markdown_headers
        ):
            raise ValueError("markdown_headers must contain distinct levels from 1 to 6")
        return self


def split_document(
    text: str, settings: DocumentSplitterSettings, *, metadata: dict[str, Any] | None = None
) -> list["Document"]:
    """Split a transcription without inference, file IO or changing its source."""
    from langchain_core.documents import Document
    from langchain_text_splitters import (
        CharacterTextSplitter,
        MarkdownHeaderTextSplitter,
        RecursiveCharacterTextSplitter,
    )

    options: dict[str, Any] = {
        "chunk_size": settings.chunk_size,
        "chunk_overlap": settings.chunk_overlap,
        "keep_separator": settings.keep_separator,
        "strip_whitespace": settings.strip_whitespace,
        "is_separator_regex": False,
    }
    splitter_type = CharacterTextSplitter if settings.type == "character" else RecursiveCharacterTextSplitter
    options["separator" if settings.type == "character" else "separators"] = (
        settings.separator if settings.type == "character" else settings.separators
    )
    if settings.length_unit == "tokens":
        splitter = splitter_type.from_tiktoken_encoder(
            encoding_name=settings.encoding, allowed_special=set(), disallowed_special=(), **options
        )
    else:
        splitter = splitter_type(**options)

    if settings.type == "markdown":
        sections = MarkdownHeaderTextSplitter(
            headers_to_split_on=[("#" * level, f"header_{level}") for level in settings.markdown_headers],
            strip_headers=settings.strip_headers,
        ).split_text(text)
        documents = [
            Document(page_content=section.page_content, metadata={**(metadata or {}), "headers": section.metadata})
            for section in sections
        ]
    else:
        documents = [Document(page_content=text, metadata=dict(metadata or {}))]
    chunks = splitter.split_documents(documents)
    if settings.type == "character":
        # CharacterTextSplitter leaves an unbroken paragraph oversized. Apply
        # the official recursive splitter to keep the configured ingestion bound.
        fallback_options = {key: value for key, value in options.items() if key != "separator"}
        fallback_options["separators"] = [""]
        if settings.length_unit == "tokens":
            fallback = RecursiveCharacterTextSplitter.from_tiktoken_encoder(
                encoding_name=settings.encoding, allowed_special=set(), disallowed_special=(), **fallback_options
            )
        else:
            fallback = RecursiveCharacterTextSplitter(**fallback_options)
        chunks = fallback.split_documents(chunks)
    for index, chunk in enumerate(chunks):
        chunk.metadata["chunk_index"] = index
    return chunks
