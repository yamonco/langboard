import { test, expect } from "@playwright/test";
for (const width of [1440, 390]) {
    test(`secure input clears material and supports cancellation at ${width}`, async ({ page }) => {
        await page.setViewportSize({ width, height: 900 });
        let posts = 0;
        let cancelled = false;
        await page.route("**/secret-input/fixture-input", async (route) => {
            const method = route.request().method();
            if (method === "POST") {
                posts++;
                expect(route.request().postDataJSON()).toEqual({ value: "fixture-sensitive" });
            }
            if (method === "DELETE") cancelled = true;
            await route.fulfill({
                json: method === "GET" ? { name: "provider/api-key", scope: "personal" } : { state: "completed", secret_ref: "secret://ref/fixture" },
            });
        });
        await page.goto("/src/pages/AccountPage/secret-input.fixture.html");
        const input = page.locator('input[type="password"]');
        await expect(input).toBeVisible();
        expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
        await page.screenshot({ path: `test-results/secret-input-${width}.png` });
        await input.fill("fixture-sensitive");
        await page.locator('button[type="submit"]').click();
        await expect(input).toHaveCount(0);
        await expect(page.getByRole("status")).toBeVisible();
        expect(posts).toBe(1);
        expect(await page.locator("body").textContent()).not.toContain("fixture-sensitive");
        await page.reload();
        await input.fill("unsaved-fixture");
        await page.locator('button[type="button"]').click();
        await expect(input).toHaveCount(0);
        await expect(page.getByRole("status")).toBeVisible();
        expect(cancelled).toBe(true);
        expect(posts).toBe(1);
    });
}
