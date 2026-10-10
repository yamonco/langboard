import { expect, test } from "@playwright/test";

for (const scenario of ["Unchanged", "Unread", "New change", "Missing receipt", "Wrong card"]) {
    test(`seen receipt: ${scenario}`, async ({ page }) => {
        await page.goto("/src/controllers/api/board/useMarkCardSeen.fixture.html");
        await expect(page.getByText("Board reads: 1", { exact: true })).toBeVisible();
        await expect(page.getByText("Reader reads: 1", { exact: true })).toBeVisible();
        await page.getByRole("button", { name: scenario, exact: true }).click();
        await expect(page.getByText(`${scenario}: pending`, { exact: true })).toBeVisible();
        await page.getByRole("button", { name: scenario === "New change" ? "Publish intervening change" : "Release receipt", exact: true }).click();
        await expect(page.getByText(`${scenario}: complete`, { exact: true })).toBeVisible();
        await expect(page.getByText(`Board reads: ${scenario === "Unchanged" ? 1 : 2}`, { exact: true })).toBeVisible();
        await expect(page.getByText("Reader reads: 2", { exact: true })).toBeVisible();
    });
}
