import { expect, test } from "@playwright/test";

test("existing relative-time hook updates immediately when account language changes", async ({ page }) => {
    await page.addInitScript(() => localStorage.setItem("lang", "en-US"));
    await page.goto("/src/core/utils/LocaleFormat.fixture.html");
    await expect(page.getByTestId("relative")).toHaveText("5 minutes ago");
    for (const [locale, relative] of [
        ["ko-KR", "5분 전"],
        ["ja-JP", "5 分前"],
        ["zh-CN", "5分钟前"],
        ["en-US", "5 minutes ago"],
    ]) {
        await page.getByRole("button", { name: locale, exact: true }).click();
        await expect(page.getByTestId("relative")).toHaveText(relative, { timeout: 5000 });
        await expect(page.locator("html")).toHaveAttribute("lang", locale);
    }
});
