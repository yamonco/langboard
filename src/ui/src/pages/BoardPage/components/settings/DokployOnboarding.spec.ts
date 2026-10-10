import { test, expect } from "@playwright/test";
const path = "/src/pages/BoardPage/components/settings/DokployOnboarding.fixture.html";
for (const width of [1920, 390])
    test(`health denial keeps owner removal available ${width}`, async ({ page }) => {
        await page.setViewportSize({ width, height: 1000 });
        await page.goto(path + "?saved&denyhealth&deny");
        await page.getByRole("combobox", { name: "Existing connection" }).selectOption("conn");
        await expect(page.getByRole("alert")).toBeVisible();
        await expect(page.getByRole("combobox", { name: "Existing connection" })).toHaveValue("conn");
        await page.getByRole("button", { name: "Load saved selections" }).click();
        await page.getByRole("button", { name: "Remove selection", exact: true }).click();
        await expect(page.getByRole("button", { name: "Remove selection", exact: true })).toHaveCount(0);
        const calls = await page.evaluate(() => (window as unknown as { dokployCalls: { url: string }[] }).dokployCalls);
        expect(calls.some((row) => row.url.endsWith("/resources"))).toBe(false);
        expect(calls.some((row) => row.url.endsWith("/remove"))).toBe(true);
    });
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

async function prepareWebhookRead(page: import("@playwright/test").Page) {
    await page.getByRole("button", { name: "Load projects" }).click();
    await page.getByRole("combobox", { name: "Project", exact: true }).selectOption("project-1");
    await page.getByRole("combobox", { name: "Environment", exact: true }).selectOption("env-1");
    await page.getByRole("checkbox").first().check();
    await page.getByRole("button", { name: "Enable read access", exact: true }).click();
    await page.getByRole("button", { name: "Confirm read access", exact: true }).click();
    await page.getByRole("button", { name: "Refresh notification health" }).click();
}
for (const width of [1920, 390])
    test(`webhook explicit configuration and receipt truth ${width}`, async ({ page }) => {
        await page.clock.install({ time: new Date("2026-10-08T01:32:03Z") });
        await page.setViewportSize({ width, height: 1080 });
        await page.goto(path + "?receipt");
        await page.getByRole("combobox", { name: "Existing connection" }).selectOption("conn");
        await expect(page.getByText("Notifications unconfigured", { exact: true })).toBeVisible();
        await prepareWebhookRead(page);
        await expect(page.getByText("Provider configuration is unknown.", { exact: false })).toBeVisible();
        await expect(page.locator("time[datetime='2026-10-08T01:02:03Z']")).toHaveText("30 minutes ago");
        await expect(page.getByRole("button", { name: "Configure notifications", exact: true })).toBeDisabled();
        await page.getByRole("button", { name: "Store webhook token securely" }).click();
        await expect(page.getByRole("link", { name: "Open secure webhook token input" })).toHaveAttribute("href", /\/secret-input\/w{43}$/);
        await page.getByRole("button", { name: "Check webhook token input" }).click();
        await page.getByLabel("Notification ID (optional)").fill("notification-1");
        await page.getByRole("button", { name: "Configure notifications", exact: true }).click();
        await page.getByRole("button", { name: "Cancel", exact: true }).click();
        expect(
            await page.evaluate(
                () =>
                    (window as unknown as { dokployCalls: { url: string }[] }).dokployCalls.filter((row) => row.url.endsWith("/webhook-config"))
                        .length
            )
        ).toBe(0);
        await page.getByRole("button", { name: "Configure notifications", exact: true }).click();
        await page.getByRole("button", { name: "Confirm notification configuration" }).click();
        await expect(page.getByText("Notifications enabled", { exact: true })).toBeVisible();
        await expect(page.getByLabel("Receiver path", { exact: true })).toHaveValue("/apps/dokploy/notifications/config");
        await expect(page.getByLabel("Webhook credential reference")).toHaveValue("");
        await page.getByRole("button", { name: "Disable notifications", exact: true }).click();
        await page.getByRole("button", { name: "Cancel", exact: true }).click();
        await page.getByRole("button", { name: "Disable notifications", exact: true }).click();
        await page.getByRole("button", { name: "Confirm disable notifications" }).click();
        await expect(page.getByText("Notifications disabled", { exact: true })).toBeVisible();
        await expect(page.locator("time[datetime='2026-10-08T01:02:03Z']")).toHaveText("30 minutes ago");
        const calls = await page.evaluate(
            () => (window as unknown as { dokployCalls: { method: string; url: string; data: unknown }[] }).dokployCalls
        );
        expect(calls.find((row) => row.url.endsWith("/webhook-config"))?.data).toEqual({
            expected_revision: "c".repeat(64),
            expected_binding_revision: "d".repeat(64),
            expected_config_revision: 0,
            credential_reference: "secret://ref/abcdefghijk",
            notification_id: "notification-1",
        });
        expect(calls.find((row) => row.url.endsWith("/webhook-disable"))?.data).toEqual({
            expected_revision: "c".repeat(64),
            expected_binding_revision: "d".repeat(64),
            expected_config_revision: 1,
        });
        expect(calls.filter((row) => row.url.endsWith("/webhook-health"))).toHaveLength(2);
        expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
        await page.screenshot({ path: `test-results/dokploy-webhook-${width}.png`, fullPage: true });
        await page.getByRole("button", { name: "Refresh notification health" }).click();
        await expect(page.getByText("Notifications disabled", { exact: true })).toBeVisible();
        await page.getByRole("combobox", { name: "Existing connection" }).selectOption("");
        await expect(page.getByText("Notifications disabled", { exact: true })).toHaveCount(0);
    });
for (const action of ["Switch board", "Remove permission"])
    test(`late webhook health discarded on ${action}`, async ({ page }) => {
        await page.goto(path + "?delayed-health&webhook-enabled");
        await page.getByRole("combobox", { name: "Existing connection" }).selectOption("conn");
        await page.getByRole("button", { name: action }).click();
        await page.waitForTimeout(500);
        await expect(page.getByText("Notifications enabled", { exact: true })).toHaveCount(0);
        await expect(page.getByLabel("Webhook credential reference")).toHaveCount(0);
    });
test("unknown receipt and revoked connection", async ({ page }) => {
    await page.goto(path);
    await page.getByRole("combobox", { name: "Existing connection" }).selectOption("conn");
    await expect(page.getByText("No authenticated receipt recorded", { exact: false })).toBeVisible();
    await page.goto(path + "?revoked");
    await page.getByRole("combobox", { name: "Existing connection" }).selectOption("conn");
    await expect(page.getByLabel("Webhook credential reference")).toBeDisabled();
    await expect(page.getByRole("button", { name: "Configure notifications", exact: true })).toBeDisabled();
});

for (const width of [1920, 390])
    test(`revoked notification receiver remains removable ${width}`, async ({ page }) => {
        await page.setViewportSize({ width, height: 1000 });
        await page.goto(path + "?revoked&webhook-enabled&receipt&deny");
        await page.getByRole("combobox", { name: "Existing connection" }).selectOption("conn");
        await expect(page.getByRole("button", { name: "Configure notifications", exact: true })).toBeDisabled();
        await expect(page.getByRole("button", { name: "Store webhook token securely" })).toBeDisabled();
        await page.getByRole("button", { name: "Disable notifications", exact: true }).click();
        await page.getByRole("button", { name: "Confirm disable notifications" }).click();
        await expect(page.getByText("Notifications disabled", { exact: true })).toBeVisible();
        await expect(page.locator("time[datetime='2026-10-08T01:02:03Z']")).toBeVisible();
        const calls = await page.evaluate(() => (window as unknown as { dokployCalls: { url: string; data: unknown }[] }).dokployCalls);
        expect(calls.find((row) => row.url.endsWith("/webhook-disable"))?.data).toEqual({
            expected_revision: "c".repeat(64),
            expected_binding_revision: "d".repeat(64),
            expected_config_revision: 7,
        });
        expect(calls.some((row) => /\/(resources|webhook-config|verify-notification)$/.test(row.url))).toBe(false);
        expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    });

for (const action of ["Switch board", "Remove permission"])
    test(`late webhook configuration discarded on ${action}`, async ({ page }) => {
        await page.goto(path + "?delayed-webhook-post");
        await page.getByRole("combobox", { name: "Existing connection" }).selectOption("conn");
        await prepareWebhookRead(page);
        await page.getByLabel("Webhook credential reference").fill("secret://ref/webhook");
        await page.getByRole("button", { name: "Configure notifications", exact: true }).click();
        await page.getByRole("button", { name: "Confirm notification configuration" }).click();
        await page.getByRole("button", { name: action }).click();
        await page.waitForTimeout(500);
        await expect(page.getByText("Notifications enabled", { exact: true })).toHaveCount(0);
        await expect(page.getByText("Changes saved.", { exact: true })).toHaveCount(0);
        await expect(page.getByLabel("Webhook credential reference")).toHaveCount(0);
    });

for (const width of [1920, 390])
    test(`initial unconfigured webhook without selection ${width}`, async ({ page }) => {
        await page.setViewportSize({ width, height: 1080 });
        await page.goto(path);
        await page.getByRole("combobox", { name: "Existing connection" }).selectOption("conn");
        await expect(page.getByText("Notifications unconfigured", { exact: true })).toBeVisible();
        await expect(page.getByRole("alert")).toHaveCount(0);
        await page.getByLabel("Webhook credential reference").fill("secret://ref/webhook");
        await expect(page.getByRole("button", { name: "Configure notifications", exact: true })).toBeDisabled();
        await expect(page.getByRole("button", { name: "Confirm notification configuration" })).toHaveCount(0);
        const calls = await page.evaluate(() => (window as unknown as { dokployCalls: { url: string }[] }).dokployCalls);
        expect(calls.some((row) => row.url.endsWith("/webhook-config"))).toBe(false);
        expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
        await page.screenshot({ path: `test-results/dokploy-webhook-initial-${width}.png`, fullPage: true });
    });

async function prepareVerification(page: import("@playwright/test").Page, query = "") {
    await page.goto(path + "?webhook-enabled&receipt&" + query);
    await page.getByRole("combobox", { name: "Existing connection" }).selectOption("conn");
    await prepareWebhookRead(page);
    await page.getByLabel("Public HTTPS callback URL").fill("https://receiver.example.invalid/proxy/apps/dokploy/notifications/config");
}
for (const width of [1920, 390])
    for (const outcome of ["matched", "mismatch", "unavailable"])
        test(`explicit provider verification ${outcome} ${width}`, async ({ page }) => {
            await page.clock.install({ time: new Date("2026-10-08T01:32:03Z") });
            await page.setViewportSize({ width, height: 1080 });
            await prepareVerification(page, outcome);
            expect(
                await page.evaluate(
                    () =>
                        (window as unknown as { dokployCalls: { url: string }[] }).dokployCalls.filter((row) => row.url.endsWith("/webhook-verify"))
                            .length
                )
            ).toBe(0);
            await page.getByRole("button", { name: "Verify notification configuration", exact: true }).click();
            await expect(page.getByRole("status")).toContainText(`Provider configuration ${outcome}`);
            await expect(page.getByText("Provider configuration is unknown.", { exact: false })).toHaveCount(0);
            await expect(page.getByRole("status").locator("time")).toHaveText("30 minutes ago");
            await expect(page.getByRole("status").locator("time")).toHaveAttribute("title", /2026/);
            await expect(page.getByText("Notifications enabled", { exact: true })).toBeVisible();
            await expect(page.locator("time[datetime='2026-10-08T01:02:03Z']")).toHaveCount(2);
            expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
            const calls = await page.evaluate(() => (window as unknown as { dokployCalls: { url: string; data: unknown }[] }).dokployCalls);
            expect(calls.filter((row) => row.url.endsWith("/webhook-verify"))).toHaveLength(1);
            expect(calls.find((row) => row.url.endsWith("/webhook-verify"))?.data).toEqual({
                expected_revision: "c".repeat(64),
                expected_binding_revision: "d".repeat(64),
                expected_config_revision: 7,
                callback_url: "https://receiver.example.invalid/proxy/apps/dokploy/notifications/config",
            });
            await expect(page.locator("body")).not.toContainText("raw-secret-provider-value");
            await page.screenshot({ path: `test-results/dokploy-verify-${outcome}-${width}.png`, fullPage: true });
            await page.getByLabel("Notification ID (optional)").fill("draft-id");
            await expect(page.getByRole("status")).toHaveCount(0);
            await expect(page.getByRole("button", { name: "Verify notification configuration", exact: true })).toBeDisabled();
        });
for (const action of ["Switch board", "Remove permission", "callback", "notification", "connection"])
    test(`late provider verification discarded after ${action}`, async ({ page }) => {
        await prepareVerification(page, "delayed-verify");
        await page.getByRole("button", { name: "Verify notification configuration", exact: true }).click();
        if (action === "callback")
            await page.getByLabel("Public HTTPS callback URL").fill("https://other.example.invalid/apps/dokploy/notifications/config");
        else if (action === "notification") await page.getByLabel("Notification ID (optional)").fill("draft-id");
        else if (action === "connection") await page.getByRole("combobox", { name: "Existing connection" }).selectOption("");
        else await page.getByRole("button", { name: action }).click();
        await page.waitForTimeout(550);
        await expect(page.getByRole("status")).toHaveCount(0);
    });
for (const query of ["invalid-verify", "stale-verify"])
    test(`invalid provider verification rejected ${query}`, async ({ page }) => {
        await prepareVerification(page, query);
        await page.getByRole("button", { name: "Verify notification configuration", exact: true }).click();
        await expect(page.getByRole("alert")).toBeVisible();
        await expect(page.getByRole("status")).toHaveCount(0);
        await expect(page.locator("body")).not.toContainText("raw-secret-provider-value");
    });
test("provider verification requires valid explicit HTTPS callback", async ({ page }) => {
    await prepareVerification(page);
    for (const url of [
        "http://receiver.example.invalid/apps/dokploy/notifications/config",
        "https://u:p@receiver.example.invalid/apps/dokploy/notifications/config",
        "https://receiver.example.invalid/a/../apps/dokploy/notifications/config",
        "https://receiver.example.invalid/apps/dokploy/notifications/config?q=1",
        "https://receiver.example.invalid/apps/dokploy/notifications/config#x",
        "https://receiver.example.invalid/apps/dokploy/notifications/%63onfig",
        "",
    ]) {
        await page.getByLabel("Public HTTPS callback URL").fill(url);
        await expect(page.getByRole("button", { name: "Verify notification configuration", exact: true })).toBeDisabled();
    }
    await page.goto(path + "?readonly&webhook-enabled");
    await expect(page.getByRole("button", { name: "Verify notification configuration", exact: true })).toHaveCount(0);
});
