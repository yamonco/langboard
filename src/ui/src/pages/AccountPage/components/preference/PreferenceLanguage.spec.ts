import { expect, test } from "@playwright/test";
for (const width of [1280, 390]) {
    test(`avatar language dropdown survives hover exit at ${width}px`, async ({ page }) => {
        await page.setViewportSize({ width, height: 850 });
        await page.route("**/account/preferred-language", (route) => route.fulfill({ status: 200, contentType: "application/json", body: "{}" }));
        await page.goto("/src/pages/AccountPage/components/preference/PreferenceLanguage.fixture.html");
        await page.getByRole("button", { name: "Open user menu" }).click();
        await page.getByRole("dialog").getByRole("button", { name: "English (US)" }).click();
        await page.mouse.move(1, 1);
        await page.waitForTimeout(700);
        await expect(page.getByRole("menuitem", { name: "한국어" })).toBeVisible();
        await page.getByRole("menuitem", { name: "한국어" }).click();
        await expect(page.locator("output")).toContainText('"preferred":"ko-KR"');
    });
}
for (const width of [1280, 390]) {
    test(`own preference saves immediately and survives reload at ${width}px`, async ({ page }) => {
        await page.setViewportSize({ width, height: 850 });
        let release: () => void = () => {};
        const pending = new Promise<void>((resolve) => {
            release = resolve;
        });
        await page.route("**/account/preferred-language", async (route) => {
            expect(route.request().method()).toBe("PUT");
            expect(route.request().postDataJSON()).toEqual({ lang: "ko-KR" });
            await pending;
            await route.fulfill({ status: 200, contentType: "application/json", body: "{}" });
        });
        await page.goto("/src/pages/AccountPage/components/preference/PreferenceLanguage.fixture.html");
        await expect(page.getByRole("heading", { name: "Default language" })).toBeVisible();
        await page.getByRole("button", { name: "English (US)" }).click();
        await page.getByRole("menuitem", { name: "한국어" }).click();
        await expect(page.getByRole("heading", { name: "기본 언어" })).toBeVisible();
        await expect(page.getByRole("button", { name: "한국어" })).toBeDisabled();
        await expect(page.locator("output")).toContainText(JSON.stringify({ preferred: "en-US" }).slice(1, -1));
        release();
        await expect(page.locator("output")).toContainText(JSON.stringify({ preferred: "ko-KR" }).slice(1, -1));
        await expect(page.getByRole("button", { name: "한국어" })).toBeEnabled();
        expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
        await page.reload();
        await expect(page.getByRole("heading", { name: "기본 언어" })).toBeVisible();
        await expect(page.locator("output")).toContainText(JSON.stringify({ preferred: "ko-KR" }).slice(1, -1));
    });
}
test("failed save restores language and leaves persisted preference unchanged", async ({ page }) => {
    await page.route("**/account/preferred-language", (route) =>
        route.fulfill({ status: 500, contentType: "application/json", body: JSON.stringify({ detail: "Save failed" }) })
    );
    await page.goto("/src/pages/AccountPage/components/preference/PreferenceLanguage.fixture.html");
    await page.getByRole("button", { name: "English (US)" }).click();
    await page.getByRole("menuitem", { name: "日本語" }).click();
    await expect(page.getByRole("heading", { name: "Default language" })).toBeVisible();
    await expect(page.locator("output")).toContainText(JSON.stringify({ preferred: "en-US" }).slice(1, -1));
    await expect(page.locator("output")).toContainText(JSON.stringify({ language: "en-US" }).slice(1, -1));
    await expect(page.getByRole("button", { name: "English (US)" })).toBeEnabled();
});

test("keyboard selection saves all supported default languages", async ({ page }) => {
    const writes: string[] = [];
    await page.route("**/account/preferred-language", async (route) => {
        writes.push(route.request().postDataJSON().lang);
        await route.fulfill({ status: 200, contentType: "application/json", body: "{}" });
    });
    await page.goto("/src/pages/AccountPage/components/preference/PreferenceLanguage.fixture.html");
    let current = "English (US)";
    for (const [language, label] of [
        ["ja-JP", "日本語"],
        ["zh-CN", "简体中文"],
        ["ko-KR", "한국어"],
        ["en-US", "English (US)"],
    ]) {
        await page.getByRole("button", { name: current }).press("Enter");
        await page.getByRole("menuitem", { name: label }).press("Enter");
        await expect(page.locator("output")).toContainText(`"preferred":"${language}"`);
        await expect(page.getByRole("button", { name: label })).toBeEnabled();
        current = label;
    }
    expect(writes).toEqual(["ja-JP", "zh-CN", "ko-KR", "en-US"]);
});
