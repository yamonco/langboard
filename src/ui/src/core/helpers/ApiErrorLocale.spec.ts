import { expect, test } from "@playwright/test";
for (const locale of ["en-US", "ko-KR", "ja-JP", "zh-CN"]) {
    test(`non-API failure has a localized message and cancellation is silent in ${locale}`, async ({ page }) => {
        await page.addInitScript((value) => localStorage.setItem("lang", value), locale);
        await page.goto("/src/core/helpers/ApiErrorLocale.fixture.html");
        await page.getByRole("button", { name: "Resource failure", exact: true }).click();
        const fallback = await page.getByTestId("fallback").innerText();
        expect(fallback).not.toBe("");
        await expect(page.locator("output")).toHaveText(fallback);
        await expect(page.locator("output")).not.toContainText("Private");
        await page.getByRole("button", { name: "Network failure", exact: true }).click();
        await expect(page.locator("output")).toHaveText(await page.getByTestId("network").innerText());
        await page.getByRole("button", { name: "Cancel", exact: true }).click();
        await expect(page.locator("output")).toHaveText("");
    });
}
