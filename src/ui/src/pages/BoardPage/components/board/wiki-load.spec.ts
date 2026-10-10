import { expect, test } from "@playwright/test";

test("wiki retry recovers without leaving the panel and retains cached rows on refresh failure", async ({ page }) => {
    await page.goto("/src/pages/BoardPage/components/board/wiki-load.fixture.html");
    await expect(page.getByRole("alert")).toContainText("Could not load wikis");
    await expect(page.getByText("No wikis", { exact: true })).toHaveCount(0);
    await page.getByRole("button", { name: "Retry", exact: true }).press("Enter");
    await expect(page.locator("output")).toHaveText("2");
    await expect(page.getByRole("button", { name: "Retry", exact: true })).toHaveCount(0);
    await page.getByRole("button", { name: "Recover server", exact: true }).click();
    await expect(page.getByRole("button", { name: "Cached wiki", exact: true })).toBeVisible();
    await expect(page.getByRole("alert")).toHaveCount(0);
    await page.getByRole("button", { name: "Fail refresh", exact: true }).click();
    await page.getByRole("button", { name: "Release request", exact: true }).click();
    await expect(page.getByRole("alert")).toContainText("Could not load wikis");
    await expect(page.getByRole("button", { name: "Cached wiki", exact: true })).toBeVisible();
    await page.getByRole("button", { name: "Retry", exact: true }).press("Enter");
    await expect(page.locator("output")).toHaveText("4");
    await page.getByRole("button", { name: "Release request", exact: true }).click();
    await expect(page.getByRole("button", { name: "Retry", exact: true })).toBeEnabled();
});
