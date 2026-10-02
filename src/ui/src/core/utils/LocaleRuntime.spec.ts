import { expect, test } from "@playwright/test";

const closeLabels: Record<string, string> = { "en-US": "Close", "ko-KR": "닫기", "ja-JP": "閉じる", "zh-CN": "关闭" };

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
        expect(state.close).toBe(closeLabels[expected]);
        expect(state.fallbackExample).toBe("Board");
        expect(state.availableTools).toBe(
            { "en-US": "Available Tools (3)", "ko-KR": "사용 가능한 도구 (3)", "ja-JP": "利用可能なツール (3)", "zh-CN": "可用工具 (3)" }[expected]
        );
        expect(state.fallback).toEqual(["en-US"]);
        expect(state.supported).toEqual(expect.arrayContaining(["en-US", "ko-KR", "ja-JP", "zh-CN"]));
    });
}

test("language changes keep document/cache canonical and load translated resources and retain English missing-resource fallback", async ({
    page,
}) => {
    await page.goto("/src/core/utils/LocaleRuntime.fixture.html");
    for (const locale of ["ko-KR", "ja-JP", "zh-CN", "zh-Hant"]) {
        await page.getByRole("button", { name: locale, exact: true }).click();
        const expected = locale === "zh-Hant" ? "en-US" : locale;
        await expect(page.locator("output")).toContainText(`"document":"${expected}"`);
        const state = JSON.parse(await page.locator("output").innerText());
        expect(state.language).toBe(expected);
        expect(state.cached).toBe(expected);
        expect(state.close).toBe(closeLabels[expected]);
        expect(state.fallbackExample).toBe("Board");
        expect(state.availableTools).toBe(
            { "en-US": "Available Tools (3)", "ko-KR": "사용 가능한 도구 (3)", "ja-JP": "利用可能なツール (3)", "zh-CN": "可用工具 (3)" }[expected]
        );
    }
});
