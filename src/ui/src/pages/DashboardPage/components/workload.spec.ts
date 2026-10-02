import { expect, test } from "@playwright/test";
for (const width of [1280, 390]) {
    test(`workload badges, state links and model updates at ${width}px`, async ({ page }) => {
        await page.setViewportSize({ width, height: 844 });
        await page.goto("/src/pages/DashboardPage/components/workload.fixture.html");
        await expect(page.getByRole("button", { name: "5 unfinished cards", exact: true })).toHaveCount(3);
        const list = page.getByRole("region", { name: "Project list", exact: true });
        await expect(list.getByRole("button", { name: "Ready: 3 unfinished cards", exact: true })).toBeVisible();
        await expect(list.getByRole("button", { name: "Active: 2 unfinished cards", exact: true })).toBeVisible();
        await expect(page.getByRole("button", { name: /Done:|Archive:/ })).toHaveCount(0);
        await page
            .getByRole("region", { name: "Favorites", exact: true })
            .getByRole("button", { name: "Unfinished by status", exact: true })
            .press("Enter");
        await page.getByRole("button", { name: "Active: 2 unfinished cards", exact: true }).last().press("Enter");
        await expect(page.getByTestId("route")).toContainText("/board/fixture?filters=unfinished%3Ayes%2Ccolumns%3Aactive");
        await page.keyboard.press("Escape");
        await page.getByRole("button", { name: "Apply live counts", exact: true }).click();
        await expect(page.getByRole("button", { name: "1 unfinished cards", exact: true })).toHaveCount(3);
        await list.getByRole("button", { name: "Ready: 0 unfinished cards", exact: true }).press("Enter");
        await expect(page.getByTestId("route")).toContainText("columns%3Aready");
        expect(await page.locator("button button").count()).toBe(0);
        expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBe(width);
    });
}
