import pytest
import tiktoken
from pydantic import ValidationError
from langboard_shared.tasks.docling.DocumentSplitter import DocumentSplitterSettings, split_document


def test_official_splitters_preserve_sources_and_apply_character_token_and_header_settings():
    text = "한국어 문서. 日本語の資料。中文文档，English document. " * 30
    settings = DocumentSplitterSettings(chunk_size=96, chunk_overlap=16)
    chunks = split_document(text, settings, metadata={"board_uid": "board", "attachment_uid": "source", "page": 2})
    assert len(chunks) > 1
    assert all(len(chunk.page_content) <= 96 for chunk in chunks)
    assert all(chunk.metadata["page"] == 2 and chunk.metadata["attachment_uid"] == "source" for chunk in chunks)
    assert [chunk.metadata["chunk_index"] for chunk in chunks] == list(range(len(chunks)))

    token_settings = DocumentSplitterSettings(chunk_size=64, chunk_overlap=8, length_unit="tokens")
    token_chunks = split_document(text + "<|endoftext|>", token_settings)
    encoder = tiktoken.get_encoding(token_settings.encoding)
    assert all(len(encoder.encode(chunk.page_content, disallowed_special=())) <= 64 for chunk in token_chunks)

    markdown = "# 원문 제목\n\n" + text + "\n\n## 하위 제목\n\n" + text
    header_chunks = split_document(
        markdown,
        DocumentSplitterSettings(type="markdown", chunk_size=96, chunk_overlap=16),
        metadata={"attachment_uid": "source", "headers": "untrusted caller value"},
    )
    assert all(isinstance(chunk.metadata["headers"], dict) for chunk in header_chunks)
    assert any(chunk.metadata["headers"].get("header_2") == "하위 제목" for chunk in header_chunks)
    assert "# 원문 제목" in header_chunks[0].page_content

    character_chunks = split_document(
        "first paragraph\n\nsecond paragraph\n\nthird paragraph",
        DocumentSplitterSettings(type="character", chunk_size=64, chunk_overlap=0, keep_separator=False),
    )
    assert "second paragraph" in character_chunks[0].page_content

    for unit in ["characters", "tokens"]:
        unbroken = "한글日本語中文abc" * 100
        bounded = split_document(
            unbroken,
            DocumentSplitterSettings(type="character", chunk_size=64, chunk_overlap=8, length_unit=unit),
            metadata={"attachment_uid": "unbroken-source", "page": 3},
        )
        assert len(bounded) > 1
        assert all(chunk.metadata["attachment_uid"] == "unbroken-source" for chunk in bounded)
        assert all(chunk.metadata["page"] == 3 for chunk in bounded)
        assert all(
            (len(chunk.page_content) if unit == "characters" else len(encoder.encode(chunk.page_content))) <= 64
            for chunk in bounded
        )

    for invalid in [
        {"chunk_size": 64, "chunk_overlap": 64},
        {"chunk_size": True},
        {"chunk_size": 10000},
        {"separators": ["unsafe fallback"]},
        {"separators": ["x" * 33, ""]},
        {"markdown_headers": [1, 1]},
        {"markdown_headers": [7]},
        {"encoding": "remote-tokenizer"},
        {"is_separator_regex": True},
    ]:
        with pytest.raises(ValidationError):
            DocumentSplitterSettings(**invalid)


def test_docling_roundtrip_keeps_page_sources_and_multilingual_text_with_configured_bounds():
    from docling_core.types.doc import BoundingBox, DocItemLabel, DoclingDocument, ProvenanceItem, Size
    from langboard_shared.tasks.docling.DocumentSplitter import split_structural_document

    document = DoclingDocument(name="Multilingual source")
    document.add_heading("원문 Source 日本語 中文")
    for page, text in [(1, "한국어 자료 English source "), (2, "日本語の資料 中文文档 ")]:
        document.add_page(page_no=page, size=Size(width=600, height=800))
        text *= 40
        document.add_text(
            label=DocItemLabel.TEXT,
            text=text,
            prov=ProvenanceItem(page_no=page, bbox=BoundingBox(l=0, t=0, r=600, b=800), charspan=(0, len(text))),
        )
    for unit in ["characters", "tokens"]:
        settings = DocumentSplitterSettings(chunk_size=64, chunk_overlap=8, length_unit=unit)
        chunks = split_structural_document(
            document.export_to_dict(), settings,
            metadata={"board_uid": "authorized-board", "attachment_uid": "source", "content_hash": "hash"},
        )
        assert len(chunks) > 2
        assert {page for chunk in chunks for page in chunk.metadata["pages"]} == {1, 2}
        assert all(chunk.metadata["board_uid"] == "authorized-board" for chunk in chunks)
        assert all(chunk.metadata["content_hash"] == "hash" for chunk in chunks)
        assert all(chunk.metadata["docling_items"] for chunk in chunks)
        assert all(chunk.metadata["headings"] == ["원문 Source 日本語 中文"] for chunk in chunks)
        assert [chunk.metadata["chunk_index"] for chunk in chunks] == list(range(len(chunks)))
        encoder = tiktoken.get_encoding(settings.encoding)
        assert all(
            (len(chunk.page_content) if unit == "characters" else len(encoder.encode(chunk.page_content))) <= 64
            for chunk in chunks
        )
        assert any("한국어" in chunk.page_content for chunk in chunks if 1 in chunk.metadata["pages"])
        assert any("日本語" in chunk.page_content for chunk in chunks if 2 in chunk.metadata["pages"])
