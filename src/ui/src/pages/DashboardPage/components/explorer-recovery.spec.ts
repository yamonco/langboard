import { expect, test } from "@playwright/test";

for (const cached of [false, true]) {
    test(`Explorer displays failed ${cached ? "refresh" : "initial load"} and recovers through Retry`, async ({ page }) => {
        await page.goto(`/src/pages/DashboardPage/components/explorer-recovery.fixture.html${cached ? "?cached" : ""}`);
        await expect(page.getByRole("alert")).toContainText("Could not load projects");
        const board = page.getByRole("button", { name: "Retained board", exact: true });
        if (cached) await expect(board).toBeVisible();
        else await expect(board).toHaveCount(0);
        await page.getByRole("button", { name: "Recover service", exact: true }).click();
        await page.getByRole("button", { name: "Retry", exact: true }).click();
        await expect(page.getByRole("alert")).toHaveCount(0);
        await expect(board).toBeVisible();
    });
}
