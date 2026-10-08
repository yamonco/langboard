import { test, expect } from "@playwright/test";
const path = "/src/pages/BoardPage/components/board/SignalInboxPanel.fixture.html";
for (const width of [1920, 390])
    test(`explicit inbox link ${width}`, async ({ page }) => {
        await page.setViewportSize({ width, height: 850 });
        await page.goto(path);
        await page.getByRole("button", { name: /GitHub · #55/ }).click();
        await page.getByRole("combobox", { name: "Card", exact: true }).selectOption("card");
        await page.getByRole("button", { name: "Link evidence", exact: true }).click();
        await expect(page.getByText("No available signals.")).toBeVisible();
        const calls = await page.evaluate(() => (window as unknown as { inboxCalls: { method: string; data: unknown }[] }).inboxCalls);
        expect(calls.find((call) => call.method === "post")?.data).toEqual({
            connection_uid: "connection",
            resource_uid: "resource",
            signal_uid: "signal",
            source_change_seq: 7,
            expected_revision: null,
        });
        expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    });
test("denial clears results, board switch resets and readonly prohibits linking", async ({ page }) => {
    await page.goto(path + "?error");
    await page.getByRole("button", { name: /GitHub · #55/ }).click();
    await page.getByRole("combobox", { name: "Card", exact: true }).selectOption("card");
    await page.getByRole("button", { name: "Link evidence", exact: true }).click();
    await expect(page.getByRole("alert")).toBeVisible();
    await expect(page.getByRole("button", { name: /GitHub · #55/ })).toHaveCount(0);
    await page.getByRole("button", { name: "Refresh", exact: true }).click();
    await expect(page.getByRole("button", { name: /GitHub · #55/ })).toBeVisible();
    await page.getByRole("button", { name: "Switch board" }).click();
    await expect(page.getByText("No available signals.")).toBeVisible();
    await page.goto(path + "?readonly");
    await expect(page.getByRole("button", { name: /GitHub · #55/ })).toBeDisabled();
    await expect(page.getByRole("button", { name: "Link evidence", exact: true })).toHaveCount(0);
});
test("Korean mobile inbox", async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 850 });
    await page.goto(path + "?lang=ko-KR");
    await expect(page.getByRole("button", { name: /GitHub · #55/ })).toBeVisible();
    await page.getByRole("button", { name: /GitHub · #55/ }).click();
    await expect(page.getByRole("combobox", { name: "카드", exact: true })).toBeVisible();
    await page.screenshot({ path: "test-results/signal-inbox-ko-390.png", fullPage: true });
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
});

for (const width of [1920, 390])
    test(`mixed provider inbox without false card actions ${width}`, async ({ page }) => {
        await page.clock.install({ time: new Date("2026-10-08T00:30:00Z") });
        await page.setViewportSize({ width, height: 1000 });
        await page.goto(path + "?mixed");
        await expect(page.getByText("Dokploy · Deployment succeeded", { exact: true })).toBeVisible();
        await expect(page.getByText("Dokploy · Deployment failed", { exact: true })).toBeVisible();
        await expect(page.getByText("Customer API", { exact: true })).toBeVisible();
        await expect(page.getByText("Customer stack", { exact: true })).toBeVisible();
        await expect(page.getByRole("button", { name: /Dokploy ·/ })).toHaveCount(0);
        await expect(page.getByRole("combobox", { name: "Card", exact: true })).toHaveCount(0);
        const deployment = page.getByText("Dokploy · Deployment succeeded", { exact: true }).locator("..");
        await expect(deployment).not.toContainText("#deployment-");
        await expect(deployment).not.toContainText("aaaa");
        await expect(deployment.locator("time")).toHaveText("30 minutes ago");
        await expect(deployment.locator("time")).toHaveAttribute("datetime", "2026-10-08T00:00:00Z");
        await expect(deployment.locator("time")).toHaveAttribute(
            "title",
            await page.evaluate(() =>
                new Intl.DateTimeFormat("en-US", { dateStyle: "medium", timeStyle: "medium" }).format(new Date("2026-10-08T00:00:00Z"))
            )
        );
        await deployment.click();
        await expect(page.getByRole("button", { name: "Link evidence", exact: true })).toHaveCount(0);
        expect(
            await page.evaluate(() => (window as unknown as { inboxCalls: { url: string }[] }).inboxCalls.some((row) => row.url.includes("/card/")))
        ).toBe(false);
        await page.screenshot({ path: `test-results/signal-inbox-mixed-${width}.png`, fullPage: true });
        expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
        await page.getByRole("button", { name: /GitHub · #55/ }).click();
        await page.getByRole("combobox", { name: "Card", exact: true }).selectOption("card");
        await page.getByRole("button", { name: "Link evidence", exact: true }).click();
        await expect(page.getByRole("button", { name: /GitHub · #55/ })).toHaveCount(0);
        await expect(page.getByText("Dokploy · Deployment succeeded", { exact: true })).toBeVisible();
    });
test("Korean mixed deployments are localized and remain read-only", async ({ page }) => {
    await page.clock.install({ time: new Date("2026-10-08T00:30:00Z") });
    await page.setViewportSize({ width: 390, height: 1000 });
    await page.goto(path + "?mixed&readonly&lang=ko-KR&false-capability");
    await expect(page.getByText("Dokploy · 배포 성공", { exact: true })).toBeVisible();
    await expect(page.getByText("Dokploy · 배포 실패", { exact: true })).toBeVisible();
    await expect(page.getByRole("button", { name: /Dokploy ·/ })).toHaveCount(0);
    await expect(page.getByRole("button", { name: /GitHub · #55/ })).toBeDisabled();
    await expect(page.getByText("30분 전").first()).toBeVisible();
    await expect(page.getByRole("combobox")).toHaveCount(0);
    expect(
        await page.evaluate(() => (window as unknown as { inboxCalls: { method: string }[] }).inboxCalls.some((row) => row.method === "post"))
    ).toBe(false);
    await page.screenshot({ path: "test-results/signal-inbox-mixed-ko-390.png", fullPage: true });
});
test("mixed inbox discards delayed old-board response", async ({ page }) => {
    await page.goto(path + "?mixed&delayed");
    await expect(page.getByRole("status")).toBeVisible();
    await page.getByRole("button", { name: "Switch board" }).click();
    await expect(page.getByText("No available signals.")).toBeVisible();
    await page.waitForTimeout(450);
    await expect(page.getByText("Dokploy · Deployment succeeded", { exact: true })).toHaveCount(0);
    await expect(page.getByRole("button", { name: /GitHub · #55/ })).toHaveCount(0);
});
test("signal socket burst batches one mixed inbox refresh", async ({ page }) => {
    await page.goto(path + "?mixed");
    await expect(page.getByText("Dokploy · Deployment succeeded", { exact: true })).toBeVisible();
    const before = await page.evaluate(() => (window as unknown as { inboxCalls: unknown[] }).inboxCalls.length);
    await page.getByRole("button", { name: "Signal burst" }).click();
    await page.waitForTimeout(250);
    expect(await page.evaluate(() => (window as unknown as { inboxCalls: unknown[] }).inboxCalls.length)).toBe(before + 1);
});
