import assert from "node:assert/strict";
import { test } from "node:test";
import { metadataDisplay } from "./MetadataDisplay.ts";

test("metadata presentation falls back per field without changing canonical values", () => {
    const canonical = { name: "Active", description: "Work in progress" };
    const translations = {
        "ko-KR": { name: "", description: "지역 설명" },
        ko: { name: "진행", description: "언어 설명" },
        en: { name: "Legacy English", description: "Legacy description" },
    };
    const before = JSON.stringify({ canonical, translations });
    assert.deepEqual(metadataDisplay(canonical, translations, "ko-KR"), { name: "진행", description: "지역 설명" });
    assert.deepEqual(metadataDisplay(canonical, translations, "fr-FR"), canonical);
    assert.deepEqual(metadataDisplay(canonical, undefined, "ja-JP"), canonical);
    assert.deepEqual(metadataDisplay({ name: "", description: "" }, translations, "fr-FR"), translations.en);
    assert.equal(JSON.stringify({ canonical, translations }), before);
});
