import { expect, test } from "@playwright/test";

for (const [cached, expected] of [
    ["ko", "ko-KR"],
    ["ja_JP", "ja-JP"],
    ["zh-Hans", "zh-CN"],
    ["zh-Hant", "en-US"],
    ["../bad", "en-US"],
]) {
    test(`initialize ${cached} as ${expected} and repair cache/document`, async ({ page }) => {
        await page.addInitScript((value) => localStorage.setItem("lang", value), cached);
        await page.goto("/src/core/utils/LocaleRuntime.fixture.html");
        await expect(page.locator("output")).toContainText(`"language":"${expected}"`);
        const state = JSON.parse(await page.locator("output").innerText());
        expect(state.document).toBe(expected);
        expect(state.cached).toBe(expected);
        expect(state.close).toBe("Close");
        expect(state.fallback).toEqual(["en-US"]);
        expect(state.supported).toEqual(expect.arrayContaining(["en-US", "ko-KR", "ja-JP", "zh-CN"]));
    });
}

test("language changes keep document/cache canonical and use English missing-resource fallback", async ({ page }) => {
    await page.goto("/src/core/utils/LocaleRuntime.fixture.html");
    for (const locale of ["ko-KR", "ja-JP", "zh-CN", "zh-Hant"]) {
        await page.getByRole("button", { name: locale, exact: true }).click();
        const expected = locale === "zh-Hant" ? "en-US" : locale;
        await expect(page.locator("output")).toContainText(`"document":"${expected}"`);
        const state = JSON.parse(await page.locator("output").innerText());
        expect(state.language).toBe(expected);
        expect(state.cached).toBe(expected);
        expect(state.close).toBe("Close");
    }
});
