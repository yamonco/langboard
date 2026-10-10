import { expect, test } from "@playwright/test";

for (const width of [1280, 390]) {
    test(`policy submits once and retains failed draft at ${width}px`, async ({ page }) => {
        await page.setViewportSize({ width, height: 850 });
        const writes: unknown[] = [];
        let fail = true;
        await page.route("**/settings/apps/governance", async (route) => {
            const headers = {
                "Access-Control-Allow-Origin": "http://127.0.0.1:4216",
                "Access-Control-Allow-Credentials": "true",
                "Access-Control-Allow-Methods": "GET,PUT,OPTIONS",
                "Access-Control-Allow-Headers": "content-type,authorization,content-encoding",
            };
            if (route.request().method() === "OPTIONS") return route.fulfill({ status: 204, headers });
            if (route.request().method() === "GET")
                return route.fulfill({
                    status: 200,
                    headers,
                    json: {
                        mode: "approved_only",
                        effective_mode: "approved_only",
                        revision: "a".repeat(64),
                    },
                });
            writes.push(route.request().postDataJSON());
            await route.fulfill({
                status: fail ? 500 : 200,
                headers,
                json: fail
                    ? { detail: "failed" }
                    : {
                          mode: "disabled",
                          effective_mode: "disabled",
                          revision: "b".repeat(64),
                      },
            });
        });
        await page.goto("/src/pages/SettingsPage/AppGovernance.fixture.html");
        await page.locator("input[value=disabled]").check();
        await page.locator("form").evaluate((form) => {
            form.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }));
            form.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }));
        });
        await expect(page.getByRole("alert")).toBeVisible();
        expect(writes).toEqual([{ mode: "disabled", expected_revision: "a".repeat(64) }]);
        await expect(page.locator("input[value=disabled]")).toBeChecked();
        fail = false;
        await page.getByRole("button", { name: "Save", exact: true }).click();
        await expect(page.getByRole("status")).toBeVisible();
        expect(writes).toHaveLength(2);
        expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    });
}
