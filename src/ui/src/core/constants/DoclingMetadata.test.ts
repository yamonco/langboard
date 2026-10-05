import assert from "node:assert/strict";
import { test } from "node:test";
import { documentDisplayTags } from "./DoclingMetadata.ts";

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
