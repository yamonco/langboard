import { test, expect } from "@playwright/test";
for (const width of [1920, 390]) {
    test(`settings role failure can recover without reload at ${width}px`, async ({ page }) => {
        await page.setViewportSize({ width, height: 844 });
        let requests = 0;
        await page.route("**/settings/roles", async (route) => {
            requests++;
            await route.fulfill({ status: requests === 1 ? 500 : 200, json: requests === 1 ? {} : { setting_role_actions: [] } });
        });
        await page.goto("/src/pages/SettingsPage/SettingsLoad.fixture.html");
        await expect(page.getByRole("alert")).toContainText("Could not load settings");
        expect(requests).toBe(1);
        await page.getByRole("button", { name: "Retry", exact: true }).press("Enter");
        await expect(page.getByText("Settings ready")).toBeVisible();
        expect(requests).toBe(2);
        expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    });
}

test("settings role request timeout leaves a retry instead of an empty gate", async ({ page }) => {
    test.setTimeout(45000);
    let requests = 0;
    await page.route("**/settings/roles", async (route) => {
        requests++;
        if (requests === 1) return;
        await route.fulfill({ json: { setting_role_actions: [] } });
    });
    await page.goto("/src/pages/SettingsPage/SettingsLoad.fixture.html");
    await expect(page.getByRole("status")).toBeVisible();
    await expect(page.getByRole("alert")).toContainText("Could not load settings", { timeout: 35000 });
    expect(requests).toBe(1);
    await page.getByRole("button", { name: "Retry", exact: true }).click();
    await expect(page.getByText("Settings ready")).toBeVisible();
    expect(requests).toBe(2);
});
