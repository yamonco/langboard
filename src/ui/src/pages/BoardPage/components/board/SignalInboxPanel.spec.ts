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
        await page.goto(path + "?mixed&nonlink");
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
    await page.goto(path + "?mixed&readonly&lang=ko-KR&nonlink");
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
    await page.goto(path + "?mixed&nonlink");
    await expect(page.getByText("Dokploy · Deployment succeeded", { exact: true })).toBeVisible();
    const before = await page.evaluate(() => (window as unknown as { inboxCalls: unknown[] }).inboxCalls.length);
    await page.getByRole("button", { name: "Signal burst" }).click();
    await page.waitForTimeout(250);
    expect(await page.evaluate(() => (window as unknown as { inboxCalls: unknown[] }).inboxCalls.length)).toBe(before + 1);
});

for (const width of [1920, 390])
    test(`explicit Dokploy inbox card evidence ${width}`, async ({ page }) => {
        await page.setViewportSize({ width, height: 1000 });
        await page.goto(path + "?mixed");
        await page.getByRole("button", { name: /Dokploy · Deployment succeeded/ }).click();
        await page.getByRole("combobox", { name: "Card", exact: true }).selectOption("card");
        await page.getByRole("button", { name: "Link evidence", exact: true }).click();
        await expect(page.getByRole("button", { name: /Dokploy · Deployment succeeded/ })).toHaveCount(0);
        await page.getByRole("button", { name: /Dokploy · Deployment failed/ }).click();
        await page.getByRole("combobox", { name: "Card", exact: true }).selectOption("card");
        await page.getByRole("button", { name: "Link evidence", exact: true }).click();
        await expect(page.getByRole("button", { name: /Dokploy · Deployment failed/ })).toHaveCount(0);
        const posts = await page.evaluate(() =>
            (window as unknown as { inboxCalls: { method: string; data: unknown }[] }).inboxCalls.filter((row) => row.method === "post")
        );
        expect(posts.map((row) => row.data)).toEqual(
            ["application", "compose"].map((type) => ({
                connection_uid: "dokploy-connection",
                resource_uid: type,
                signal_uid: `dokploy-${type}`,
                source_change_seq: 7,
                expected_revision: null,
            }))
        );
        await expect(page.getByRole("button", { name: /GitHub · #55/ })).toBeVisible();
        await page.screenshot({ path: `test-results/signal-inbox-dokploy-link-${width}.png`, fullPage: true });
        await page.goto(path + "?mixed&readonly");
        await expect(page.getByRole("button", { name: /Dokploy · Deployment succeeded/ })).toBeDisabled();
        await expect(page.getByRole("button", { name: "Link evidence", exact: true })).toHaveCount(0);
    });

for (const width of [1920, 390])
    for (const provider of ["github", "dokploy"])
        test(`explicit new card ${provider} ${width}`, async ({ page }) => {
            await page.setViewportSize({ width, height: 1000 });
            await page.goto(path + "?mixed");
            await page.getByRole("button", { name: provider === "github" ? /GitHub · #55/ : /Dokploy · Deployment succeeded/ }).click();
            const posts = () =>
                page.evaluate(
                    () => (window as unknown as { inboxCalls: { method: string }[] }).inboxCalls.filter((row) => row.method === "post").length
                );
            expect(await posts()).toBe(0);
            await page.getByRole("button", { name: "New card from signal", exact: true }).click();
            const title = page.getByRole("textbox", { name: "Card title", exact: true });
            await expect(title).toHaveValue(provider === "github" ? "GitHub · Check" : "Dokploy · Customer API · Deployment succeeded");
            const column = page.getByRole("combobox", { name: "Column", exact: true });
            await expect(column.locator("option")).toHaveText(["Choose a column", "Ready", "In progress"]);
            await expect(page.getByRole("button", { name: "Create card", exact: true })).toBeDisabled();
            await column.selectOption("ready");
            await title.fill("   ");
            await expect(page.getByRole("button", { name: "Create card", exact: true })).toBeDisabled();
            await title.fill("  Investigate deployment  ");
            expect(await posts()).toBe(0);
            await page.screenshot({ path: `test-results/signal-inbox-new-${provider}-${width}.png`, fullPage: true });
            expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
            await page.getByRole("button", { name: "Create card", exact: true }).click();
            await expect(page.getByText("Card created with signal evidence.", { exact: true })).toBeVisible();
            const calls = await page.evaluate(
                () => (window as unknown as { inboxCalls: { url: string; method: string; data: unknown }[] }).inboxCalls
            );
            expect(calls.filter((row) => row.method === "post")).toHaveLength(1);
            expect(calls.find((row) => row.url.endsWith("/inbox/card"))?.data).toEqual({
                connection_uid: provider === "github" ? "connection" : "dokploy-connection",
                resource_uid: provider === "github" ? "resource" : "application",
                signal_uid: provider === "github" ? "signal" : "dokploy-application",
                project_column_uid: "ready",
                title: "Investigate deployment",
            });
            expect(await page.evaluate(() => (window as unknown as { creationCallbacks: string[] }).creationCallbacks)).toEqual(["created-card"]);
        });
test("new card replay receipt, cancellation and current columns", async ({ page }) => {
    await page.goto(path + "?mixed&replay");
    await page.getByRole("button", { name: /Dokploy · Deployment succeeded/ }).click();
    await page.getByRole("button", { name: "New card from signal", exact: true }).click();
    await page.getByRole("combobox", { name: "Column", exact: true }).selectOption("ready");
    await page.getByRole("button", { name: "Archive ready column" }).click();
    await expect(page.getByRole("button", { name: "Create card", exact: true })).toBeDisabled();
    await expect(page.getByRole("combobox", { name: "Column", exact: true }).locator("option")).toHaveText(["Choose a column", "In progress"]);
    await page.getByRole("button", { name: "Cancel", exact: true }).click();
    expect(
        await page.evaluate(() => (window as unknown as { inboxCalls: { method: string }[] }).inboxCalls.some((row) => row.method === "post"))
    ).toBe(false);
    await page.getByRole("button", { name: "New card from signal", exact: true }).click();
    await page.getByRole("combobox", { name: "Column", exact: true }).selectOption("progress");
    await page.getByRole("button", { name: "Create card", exact: true }).click();
    await expect(page.getByText("Existing card returned with signal evidence.", { exact: true })).toBeVisible();
});
test("new card failure clears form and receipt", async ({ page }) => {
    await page.goto(path + "?mixed&error");
    await page.getByRole("button", { name: /Dokploy · Deployment succeeded/ }).click();
    await page.getByRole("button", { name: "New card from signal", exact: true }).click();
    await page.getByRole("combobox", { name: "Column", exact: true }).selectOption("ready");
    await page.getByRole("button", { name: "Create card", exact: true }).click();
    await expect(page.getByRole("alert")).toBeVisible();
    await expect(page.getByRole("textbox", { name: "Card title", exact: true })).toHaveCount(0);
    expect(await page.evaluate(() => (window as unknown as { creationCallbacks: string[] }).creationCallbacks)).toEqual([]);
});
for (const change of ["Switch board", "Remove edit access"])
    test(`new card delayed receipt discarded after ${change}`, async ({ page }) => {
        await page.goto(path + "?mixed&delayed-create");
        await page.getByRole("button", { name: /Dokploy · Deployment succeeded/ }).click();
        await page.getByRole("button", { name: "New card from signal", exact: true }).click();
        await page.getByRole("combobox", { name: "Column", exact: true }).selectOption("ready");
        await page.getByRole("button", { name: "Create card", exact: true }).click();
        await expect(page.getByText("Loading signals…")).toBeVisible();
        await page.getByRole("button", { name: change, exact: true }).click();
        await page.waitForTimeout(450);
        await expect(page.getByText("Card created with signal evidence.", { exact: true })).toHaveCount(0);
        expect(await page.evaluate(() => (window as unknown as { creationCallbacks: string[] }).creationCallbacks)).toEqual([]);
    });
test("Korean new-card form and readonly", async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 1000 });
    await page.goto(path + "?mixed&lang=ko-KR");
    await page.getByRole("button", { name: /Dokploy · 배포 성공/ }).click();
    await page.getByRole("button", { name: "신호에서 새 카드 만들기", exact: true }).click();
    await expect(page.getByRole("textbox", { name: "카드 제목", exact: true })).toHaveValue("Dokploy · Customer API · 배포 성공");
    await page.getByRole("combobox", { name: "열", exact: true }).selectOption("ready");
    await page.screenshot({ path: "test-results/signal-inbox-new-ko-390.png", fullPage: true });
    await page.goto(path + "?mixed&readonly");
    await expect(page.getByRole("button", { name: "New card from signal", exact: true })).toHaveCount(0);
    expect(
        await page.evaluate(() => (window as unknown as { inboxCalls: { method: string }[] }).inboxCalls.some((row) => row.method === "post"))
    ).toBe(false);
});
