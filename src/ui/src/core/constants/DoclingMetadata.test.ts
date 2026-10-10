import assert from "node:assert/strict";
import { test } from "node:test";
import { DOCLING_DOCUMENTS_METADATA_KEY, documentDisplayTags, pendingDocument } from "./DoclingMetadata.ts";

test("attachment tags use the user language with English defaults and fallback, bounded and deduplicated", () => {
    const content = { search_keywords: { ko: ["문서", "검색"], en: ["#document", " search ", "document", "a", "b", "c", "d"], ja: [] } };
    assert.deepEqual(documentDisplayTags(content, "ko-KR"), ["문서", "검색"]);
    assert.deepEqual(documentDisplayTags(content), ["document", "search", "a", "b", "c"]);
    assert.deepEqual(documentDisplayTags(content, "ja-JP"), documentDisplayTags(content));
    assert.deepEqual(documentDisplayTags(content, "fr-FR"), documentDisplayTags(content));
    assert.deepEqual(documentDisplayTags({ search_keywords: { ko: [false, "", "x".repeat(81)], en: ["fallback"] } }, "ko"), ["fallback"]);
    assert.deepEqual(documentDisplayTags({}), []);
    assert.deepEqual(documentDisplayTags({ search_keywords: [] }), []);
});

test("card progress includes explicit embedding work without resurrecting failed or completed work", () => {
    const metadata = (entries: unknown[]) => ({ [DOCLING_DOCUMENTS_METADATA_KEY]: JSON.stringify(entries) });
    const entry = { attachment_uid: "attachment", status: "indexed", content: {}, embedding: { status: "pending" } };
    assert.deepEqual(pendingDocument(metadata([entry])), entry);
    assert.equal(pendingDocument(metadata([{ ...entry, embedding: { status: "failed" } }])), undefined);
    assert.equal(pendingDocument(metadata([{ ...entry, embedding: { status: "indexed" } }])), undefined);
    const transcription = { ...entry, attachment_uid: "transcribing", status: "processing", embedding: undefined };
    assert.equal(pendingDocument(metadata([transcription, entry]))?.attachment_uid, "transcribing");
    assert.equal(pendingDocument(undefined), undefined);
    assert.equal(pendingDocument({ [DOCLING_DOCUMENTS_METADATA_KEY]: "invalid" }), undefined);
});
