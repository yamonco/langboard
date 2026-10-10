import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { test } from "node:test";
import { createInstance } from "i18next";

test("deadline countdown formats numeric counts through the actual four-language resources", async () => {
    const locales = ["en-US", "ko-KR", "ja-JP", "zh-CN"];
    const resources = Object.fromEntries(await Promise.all(locales.map(async (locale) => [
        locale,
        { translation: { card: JSON.parse(await readFile(new URL(`../../assets/locales/${locale}/card.json`, import.meta.url), "utf8")) } },
    ])));
    const i18n = createInstance();
    await i18n.init({ resources, fallbackLng: "en-US", interpolation: { escapeValue: false } });
    for (const lng of locales) {
        for (const count of [1, 2, 1234]) {
            assert.equal(i18n.t("card.D-{{count}}", { lng, count }), `D-${new Intl.NumberFormat(lng).format(count)}`);
        }
        assert.equal(i18n.t("card.D-Day", { lng }), resources[lng].translation.card["D-Day"]);
    }
});
