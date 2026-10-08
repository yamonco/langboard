import { test, expect } from "@playwright/test";
const path = "/src/pages/BoardPage/components/settings/DokployOnboarding.fixture.html";
for (const width of [1920, 390])
    test(`secure registration and hierarchy selection ${width}`, async ({ page }) => {
        await page.clock.install({ time: new Date("2026-10-08T01:32:03Z") });
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
        const refresh = page.getByRole("button", { name: "Refresh deployments" }).first();
        await expect(page.getByText("app-1 · Application", { exact: true })).toHaveCount(0);
        await expect(page.getByText("Customer API · Application", { exact: true })).toBeVisible();
        await expect(refresh).toBeDisabled();
        await page.getByRole("button", { name: "Enable read access", exact: true }).click();
        await expect(page.getByText("Read access applies to all selected Dokploy resources", { exact: false })).toBeVisible();
        expect(
            await page.evaluate(
                () => (window as unknown as { dokployCalls: { url: string }[] }).dokployCalls.filter((row) => row.url.endsWith("/enable-read")).length
            )
        ).toBe(0);
        await page.getByRole("button", { name: "Cancel", exact: true }).click();
        await page.getByRole("button", { name: "Enable read access", exact: true }).click();
        const beforeConsent = await page.evaluate(() => (window as unknown as { dokployCalls: unknown[] }).dokployCalls.length);
        await page.getByRole("button", { name: "Confirm read access", exact: true }).click();
        await expect(page.getByText("Board read access enabled.")).toBeVisible();
        expect(await page.evaluate(() => (window as unknown as { dokployCalls: unknown[] }).dokployCalls.length)).toBe(beforeConsent + 1);
        await refresh.click();
        await expect(page.getByText("Deployment succeeded · Success")).toBeVisible();
        const occurrence = page.locator("time[datetime='2026-10-08T01:02:03.000000+00:00']");
        await expect(occurrence).toHaveText("30 minutes ago");
        await expect(occurrence).toHaveAttribute(
            "title",
            await page.evaluate(() =>
                new Intl.DateTimeFormat("en-US", { dateStyle: "medium", timeStyle: "medium" }).format(new Date("2026-10-08T01:02:03Z"))
            )
        );
        await expect(page.getByText("Results truncated to the latest 25 events.")).toBeVisible();
        await expect(page.getByText("sensitive-provider-log")).toHaveCount(0);
        await expect(page.getByText("sensitive-provider-title")).toHaveCount(0);
        await page.getByRole("checkbox").nth(1).check();
        await expect(page.getByText("Deployment succeeded · Success")).toHaveCount(0);
        await page.getByRole("button", { name: "Refresh deployments" }).nth(1).click();
        await expect(page.getByText("Deployment succeeded · Success")).toBeVisible();
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
        expect(calls.find((row) => row.url.endsWith("/enable-read"))?.data).toEqual({
            expected_revision: "a".repeat(64),
            expected_binding_revision: "b".repeat(64),
        });
        expect(calls.find((row) => row.url.endsWith("/resource/refresh"))?.data).toEqual({
            expected_revision: "a".repeat(64),
            expected_access_revision: 3,
        });
        expect(calls.find((row) => row.url.endsWith("/compose-resource/refresh"))?.data).toEqual({
            expected_revision: "a".repeat(64),
            expected_access_revision: 4,
        });
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

for (const action of ["consent", "refresh"])
    test(`board switch discards inflight ${action}`, async ({ page }) => {
        await page.goto(path + "?delayed");
        await page.getByRole("combobox", { name: "Existing connection" }).selectOption("conn");
        await page.getByRole("button", { name: "Load projects" }).click();
        await page.getByRole("combobox", { name: "Project", exact: true }).selectOption("project-1");
        await page.getByRole("combobox", { name: "Environment", exact: true }).selectOption("env-1");
        await page.getByRole("checkbox").first().check();
        await page.getByRole("button", { name: "Enable read access", exact: true }).click();
        await page.getByRole("button", { name: "Confirm read access", exact: true }).click();
        if (action === "refresh") {
            await expect(page.getByText("Board read access enabled.")).toBeVisible();
            await page.getByRole("button", { name: "Refresh deployments" }).click();
        }
        await expect(page.getByText("Loading...", { exact: true })).toBeVisible();
        await page.getByRole("button", { name: "Switch board" }).click();
        await page.waitForTimeout(450);
        await expect(page.getByText("Board read access enabled.")).toHaveCount(0);
        await expect(page.getByText("Deployment succeeded · Success")).toHaveCount(0);
        await expect(page.getByRole("button", { name: "Refresh deployments" })).toHaveCount(0);
    });
test("connection change clears consent and deployment results", async ({ page }) => {
    await page.goto(path);
    await page.getByRole("combobox", { name: "Existing connection" }).selectOption("conn");
    await page.getByRole("button", { name: "Load projects" }).click();
    await page.getByRole("combobox", { name: "Project", exact: true }).selectOption("project-1");
    await page.getByRole("combobox", { name: "Environment", exact: true }).selectOption("env-1");
    await page.getByRole("checkbox").first().check();
    await page.getByRole("button", { name: "Enable read access", exact: true }).click();
    await page.getByRole("combobox", { name: "Existing connection" }).selectOption("");
    await expect(page.getByRole("button", { name: "Confirm read access", exact: true })).toHaveCount(0);
    await expect(page.getByRole("button", { name: "Refresh deployments" })).toHaveCount(0);
    await page.getByRole("combobox", { name: "Existing connection" }).selectOption("conn");
    await page.getByRole("button", { name: "Load projects" }).click();
    await page.getByRole("button", { name: "Enable read access", exact: true }).click();
    await page.getByRole("button", { name: "Confirm read access", exact: true }).click();
    await page.getByRole("button", { name: "Refresh deployments" }).click();
    await expect(page.getByText("Deployment succeeded · Success")).toBeVisible();
    await page.getByRole("combobox", { name: "Existing connection" }).selectOption("");
    await expect(page.getByText("Deployment succeeded · Success")).toHaveCount(0);
    await expect(page.getByText("Board read access enabled.")).toHaveCount(0);
});
