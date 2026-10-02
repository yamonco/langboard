import { expect, test } from "@playwright/test";
for (const width of [1280, 700, 390]) {
    test(`recent views keep projects accessible at ${width}px`, async ({ page }) => {
        await page.setViewportSize({ width, height: 844 });
        await page.goto("/src/pages/DashboardPage/components/recent-cards.fixture.html");
        const recent = page.getByRole("region", { name: "Recent cards", exact: true });
        await expect(recent.getByRole("button", { name: /^Card \d+$/ })).toHaveCount(10);
        await expect(recent.getByRole("button", { name: "Card 0", exact: true })).toHaveCount(0);
        const projects = page.locator("[data-explorer-project-list]");
        const measure = () => projects.evaluate((e) => ({ height: e.clientHeight, bottom: e.getBoundingClientRect().bottom }));
        expect((await measure()).height).toBeGreaterThanOrEqual(96);
        expect((await measure()).bottom).toBeLessThanOrEqual(844);
        await recent.getByRole("button", { name: "Show older cards (4)", exact: true }).press("Enter");
        await expect(recent.getByRole("button", { name: /^Card \d+$/ })).toHaveCount(14);
        expect((await measure()).height).toBeGreaterThanOrEqual(96);
        await recent.getByRole("button", { name: "Card 0", exact: true }).click();
        await expect(page.getByTestId("route")).toHaveText("/board/fixture/0");
        await page.getByRole("button", { name: "Read oldest again", exact: true }).click();
        await recent.getByRole("button", { name: "Show fewer cards", exact: true }).click();
        await expect(recent.getByRole("button", { name: /^Card \d+$/ })).toHaveCount(10);
        await expect(recent.getByRole("button", { name: /^Card \d+$/ }).first()).toHaveText("Card 0");
        expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBe(width);
        expect(await page.locator("button button").count()).toBe(0);
        await page.goto("/src/pages/DashboardPage/components/recent-cards.fixture.html?count=10");
        await expect(recent.getByRole("button", { name: /Show older|Show fewer/ })).toHaveCount(0);
        await expect(recent.getByRole("button", { name: /^Card \d+$/ })).toHaveCount(10);
    });
}
