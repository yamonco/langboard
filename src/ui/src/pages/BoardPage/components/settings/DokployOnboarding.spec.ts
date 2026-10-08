import { test, expect } from "@playwright/test";
const path = "/src/pages/BoardPage/components/settings/DokployOnboarding.fixture.html";
for (const width of [1920, 390])
    test(`secure registration and hierarchy selection ${width}`, async ({ page }) => {
        await page.setViewportSize({ width, height: 1000 });
        await page.goto(path + "?new");
        await page.getByLabel("Instance URL", { exact: true }).fill("https://deploy.example.invalid");
        await page.getByRole("button", { name: "Store API token securely" }).click();
        await expect(page.getByRole("link", { name: "Open secure token input" })).toHaveAttribute("href", /\/secret-input\/s{43}$/);
        await page.getByRole("button", { name: "Check token input" }).click();
        await page.getByRole("button", { name: "Connect", exact: true }).click();
        await page.getByRole("button", { name: "Load projects" }).click();
        await page.getByRole("combobox", { name: "Project", exact: true }).selectOption("project-1");
        await page.getByRole("combobox", { name: "Environment", exact: true }).selectOption("env-1");
        const checkbox = page.getByRole("checkbox").first();
        await checkbox.check();
        await expect(checkbox).toBeChecked();
        await checkbox.uncheck();
        await expect(checkbox).not.toBeChecked();
        await checkbox.check();
        const calls = await page.evaluate(
            () => (window as unknown as { dokployCalls: { method: string; url: string; data: unknown }[] }).dokployCalls
        );
        expect(calls.find((row) => row.method === "post" && row.url.endsWith("/connections"))?.data).toEqual({
            instance_url: "https://deploy.example.invalid",
            credential_reference: "secret://ref/abcdefghijk",
        });
        const selections = calls.filter((row) => row.method === "post" && row.url.endsWith("/selected"));
        expect(selections[0].data).toMatchObject({
            resource_type: "application",
            external_id: "app-1",
            external_project_id: "project-1",
            environment_id: "env-1",
            expected_resource_revision: null,
        });
        expect(selections[1].data).toMatchObject({ expected_resource_revision: 2 });
        expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
        await page.screenshot({ path: `test-results/dokploy-onboarding-${width}.png`, fullPage: true });
        await page.getByRole("button", { name: "Disconnect", exact: true }).click();
        await expect(page.getByText("Disconnect external access on every board.", { exact: false })).toBeVisible();
        await page.getByRole("button", { name: "Confirm disconnect" }).click();
        await expect(page.getByRole("button", { name: "Connect", exact: true })).toBeVisible();
    });
test("read only sends no requests", async ({ page }) => {
    await page.goto(path + "?readonly");
    await expect(page.getByRole("button", { name: "Store API token securely" })).toBeDisabled();
    expect(await page.evaluate(() => (window as unknown as { dokployCalls: unknown[] }).dokployCalls.length)).toBe(0);
});
test("denial clears stale provider data", async ({ page }) => {
    await page.goto(path + "?deny");
    await page.getByRole("combobox", { name: "Existing connection" }).selectOption("conn");
    await page.getByRole("button", { name: "Load projects" }).click();
    await expect(page.getByRole("alert")).toBeVisible();
    await expect(page.getByRole("combobox", { name: "Existing connection" })).toHaveValue("");
});
test("board switch discards inflight response", async ({ page }) => {
    await page.goto(path + "?delayed");
    await page.getByRole("combobox", { name: "Existing connection" }).selectOption("conn");
    await page.getByRole("button", { name: "Load projects" }).click();
    await expect(page.getByRole("status")).toBeVisible();
    await page.getByRole("button", { name: "Switch board" }).click();
    await page.waitForTimeout(450);
    await expect(page.getByRole("combobox", { name: "Project", exact: true })).toHaveCount(0);
    const calls = await page.evaluate(() => (window as unknown as { dokployCalls: { url: string }[] }).dokployCalls);
    expect(calls.some((row) => row.url === "/board/fixture/settings/apps/dokploy/connections/conn/selected")).toBe(false);
});
