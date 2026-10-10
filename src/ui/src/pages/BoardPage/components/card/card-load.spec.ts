import { expect, test } from "@playwright/test";

test("failed card load exposes recovery, deduplicates pending retries, and remains closable", async ({ page }) => {
    await page.goto("/src/pages/BoardPage/components/card/card-load.fixture.html");
    await expect(page.getByRole("alert")).toContainText("Could not load card");
    await expect(page.locator("output")).toHaveText("1");
    await page.getByRole("button", { name: "Retry", exact: true }).click();
    await expect(page.locator("output")).toHaveText("2");
    await expect(page.getByRole("button", { name: "Retry", exact: true })).toHaveCount(0);
    await expect(page.getByRole("button", { name: "Close", exact: true })).toBeVisible();
    await page.getByRole("button", { name: "Release retry", exact: true }).click();
    await expect(page.getByRole("alert")).toContainText("Could not load card");
    await expect(page.locator("output")).toHaveText("2");
    await page.getByRole("button", { name: "Close", exact: true }).click();
    await expect(page.getByText("Card closed", { exact: true })).toBeVisible();
});
