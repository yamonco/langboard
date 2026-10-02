import { expect, test } from "@playwright/test";
test("server language applies after every login and direct account switch despite legacy marker", async ({ page }) => {
    await page.addInitScript(() => {
        localStorage.setItem("lang", "zh-CN");
        localStorage.setItem("has-set-lang-langboard", "true");
    });
    await page.goto("/src/core/providers/AuthLanguage.fixture.html");
    await page.getByRole("button", { name: "Login A", exact: true }).click();
    await expect(page.locator("output")).toContainText(JSON.stringify({ user: "user-a", language: "ko-KR" }));
    await page.getByRole("button", { name: "Local Chinese" }).click();
    await expect(page.locator("output")).toContainText(JSON.stringify({ language: "zh-CN" }).slice(1, -1));
    await page.getByRole("button", { name: "Refresh A" }).click();
    await expect(page.locator("output")).toContainText(JSON.stringify({ language: "zh-CN" }).slice(1, -1));
    await page.getByRole("button", { name: "Logout" }).click();
    await expect(page.locator("output")).toContainText(JSON.stringify({ user: null }).slice(1, -1));
    await page.getByRole("button", { name: "Login A", exact: true }).click();
    await expect(page.locator("output")).toContainText(JSON.stringify({ language: "ko-KR" }).slice(1, -1));
    await page.getByRole("button", { name: "Login B", exact: true }).click();
    await expect(page.locator("output")).toContainText(JSON.stringify({ user: "user-b", language: "ja-JP" }));
    expect(await page.evaluate(() => document.documentElement.lang)).toBe("ja-JP");
});
test("unset preference preserves detected cache and invalid preference falls back to English", async ({ page }) => {
    await page.addInitScript(() => localStorage.setItem("lang", "zh-CN"));
    await page.goto("/src/core/providers/AuthLanguage.fixture.html");
    await page.getByRole("button", { name: "Login unset" }).click();
    await expect(page.locator("output")).toContainText(JSON.stringify({ user: "user-unset", language: "zh-CN" }));
    await page.getByRole("button", { name: "Login invalid" }).click();
    await expect(page.locator("output")).toContainText(JSON.stringify({ user: "user-invalid", language: "en-US" }));
});
