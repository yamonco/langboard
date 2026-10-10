import assert from "node:assert/strict";
import { test } from "node:test";
import { DEFAULT_LOCALE, FALLBACK_LOCALE, normalizeLocale, SUPPORTED_LOCALES } from "./LocalePolicy.ts";

test("canonical browser aliases preserve supported language meaning", () => {
    for (const value of ["ko", "KO-kr", "ko_KR", " ko-KR "]) assert.equal(normalizeLocale(value), "ko-KR");
    for (const value of ["ja", "JA-jp", "ja_JP"]) assert.equal(normalizeLocale(value), "ja-JP");
    for (const value of ["zh", "ZH-cn", "zh_CN", "zh-Hans", "zh-Hans-CN"]) assert.equal(normalizeLocale(value), "zh-CN");
    for (const value of SUPPORTED_LOCALES) assert.equal(normalizeLocale(value), value);
});

test("unsupported Traditional Chinese and malformed cached preferences use English", () => {
    for (const value of ["zh-TW", "zh-HK", "zh-Hant", "zh-Hant-CN", "zh-MO", "fr-FR", "../ko", "ko_KR;bad", "", null, 42]) {
        assert.equal(normalizeLocale(value), "en-US");
    }
    assert.equal(DEFAULT_LOCALE, "en-US");
    assert.equal(FALLBACK_LOCALE, "en-US");
});
