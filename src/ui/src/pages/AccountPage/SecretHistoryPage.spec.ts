import { test, expect } from "@playwright/test";
for (const width of [1440, 390]) {
    test(`history pagination clears prior rows after denial at ${width}`, async ({ page }) => {
        await page.setViewportSize({ width, height: 900 });
        let calls = 0;
        await page.route("**/secret-references/fixture/history*", async (route) => {
            calls++;
            const cursor = new URL(route.request().url()).searchParams.get("cursor");
            if (calls === 3) return route.fulfill({ status: 404, json: {} });
            expect(cursor).toBe(calls === 1 ? null : "next-1");
            await route.fulfill({
                json: {
                    items: [
                        {
                            uid: `event-${calls}`,
                            action: calls === 1 ? "rotated" : "created",
                            created_at: "2026-10-08T00:00:00Z",
                            actor_uid: "actor-fixture",
                            source_kind: "api",
                            revision_before: calls === 1 ? 0 : null,
                            revision_after: calls === 1 ? 1 : 0,
                        },
                    ],
                    next_cursor: `next-${calls}`,
                },
            });
        });
        await page.goto("/src/pages/AccountPage/secret-history.fixture.html");
        await expect(page.locator("li")).toHaveCount(1);
        await expect(page.getByText("Value replaced", { exact: true })).toBeVisible();
        expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
        await page.screenshot({ path: `test-results/secret-history-${width}.png` });
        await page.getByRole("button", { name: "Older events" }).click();
        await expect(page.locator("li")).toHaveCount(2);
        await page.getByRole("button", { name: "Older events" }).click();
        await expect(page.getByRole("alert")).toBeVisible();
        await expect(page.locator("li")).toHaveCount(0);
        expect(calls).toBe(3);
    });
}
