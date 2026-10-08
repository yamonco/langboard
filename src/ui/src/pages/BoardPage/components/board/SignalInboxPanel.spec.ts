import { test, expect } from "@playwright/test";
const path = "/src/pages/BoardPage/components/board/SignalInboxPanel.fixture.html";
for (const width of [1440, 390])
    test(`explicit inbox link ${width}`, async ({ page }) => {
        await page.setViewportSize({ width, height: 850 });
        await page.goto(path);
        await page.getByRole("button", { name: /GitHub · #55/ }).click();
        await page.getByRole("combobox", { name: "Card", exact: true }).selectOption("card");
        await page.getByRole("button", { name: "Link evidence", exact: true }).click();
        await expect(page.getByText("No available unlinked checks.")).toBeVisible();
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
    await expect(page.getByText("No available unlinked checks.")).toBeVisible();
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
