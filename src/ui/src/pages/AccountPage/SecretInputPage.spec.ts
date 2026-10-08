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
                json:
                    method === "GET"
                        ? { name: "provider/api-key", scope: "personal", operation: "rotate" }
                        : { state: "completed", secret_ref: "secret://ref/fixture" },
            });
        });
        await page.goto("/src/pages/AccountPage/secret-input.fixture.html");
        const input = page.locator('input[type="password"]');
        await expect(input).toBeVisible();
        await expect(page.getByText("Replace existing secret value", { exact: false })).toBeVisible();
        expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
        await page.screenshot({ path: `test-results/secret-input-${width}.png` });
        await input.fill("fixture-sensitive");
        await page.locator('button[type="submit"]').click();
        await expect(input).toHaveCount(0);
        await expect(page.getByRole("status")).toBeVisible();
        expect(posts).toBe(1);
        await expect(page.getByRole("link", { name: "Secret history" })).toHaveAttribute("href", "/secret-references/fixture/history");
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

for (const status of [200, 422, 503]) {
    test(`secret transport does not gzip or replay material on ${status}`, async ({ page }) => {
        await page.goto("/src/pages/AccountPage/secret-input.fixture.html");
        let posts = 0;
        let refreshes = 0;
        await page.route("**/secret-input/transport-proof", async (route) => {
            posts++;
            expect(route.request().headers()["content-encoding"]).toBeUndefined();
            expect(route.request().postDataJSON().value.length).toBe(4096);
            await route.fulfill({ status, json: { state: "completed" } });
        });
        await page.route("**/auth/refresh", async (route) => {
            refreshes++;
            await route.fulfill({ status: 401, json: {} });
        });
        const result = await page.evaluate(async () => {
            const path = "/src/core/helpers/Api.ts";
            const { api, submitSecretInput } = await import(path);
            api.defaults.baseURL = location.origin;
            try {
                const response = await submitSecretInput("/secret-input/transport-proof", "x".repeat(4096));
                return { status: response.status, retained: !!response.config.data, message: "" };
            } catch (error) {
                return { status: "failed", retained: JSON.stringify(error).includes("xxxxxxxx"), message: String(error) };
            }
        });
        expect(posts).toBe(1);
        expect(refreshes).toBe(0);
        expect(result.retained).toBe(false);
        if (status === 200) expect(result.status).toBe(200);
        else expect(result.message).toBe("Error: Secret input failed");
    });
}
