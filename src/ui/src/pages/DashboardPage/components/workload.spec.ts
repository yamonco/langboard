import { expect, test } from "@playwright/test";
for (const width of [1280, 390]) {
    test(`workload graphs, state links and model updates at ${width}px`, async ({ page }) => {
        await page.setViewportSize({ width, height: 844 });
        await page.goto("/src/pages/DashboardPage/components/workload.fixture.html");
        await expect(page.getByLabel("30 open cards", { exact: true })).toHaveCount(3);
        const list = page.getByRole("region", { name: "Project list", exact: true });
        await expect(list.getByRole("button", { name: "Ready: 1 unfinished card", exact: true })).toBeVisible();
        await expect(list.getByRole("button", { name: "Active: 4 unfinished cards", exact: true })).toBeVisible();
        await expect(page.getByRole("button", { name: /Done:|Archive:/ })).toHaveCount(0);
        const ready = list.locator("[data-workload-column=ready]");
        const active = list.locator("[data-workload-column=active]");
        await expect(ready).toHaveAttribute("data-workload-max", "4");
        await expect(active).toHaveAttribute("data-workload-max", "4");
        await expect(list.locator("[data-workload-column=review]")).toHaveAttribute("data-workload-max", "4");
        await expect(list.locator("[data-workload-column=request]")).toHaveAttribute("data-workload-max", "4");
        expect(await list.locator("[data-workload-column=review] span").evaluate((element) => Number.parseFloat(element.style.height))).toBeCloseTo(
            50
        );
        expect(await list.locator("[data-workload-column=request] span").evaluate((element) => Number.parseFloat(element.style.height))).toBeCloseTo(
            75
        );
        await expect(list.getByText("Ready", { exact: true })).toHaveCount(0);
        expect(await ready.locator("span").evaluate((element) => Number.parseFloat(element.style.height))).toBeCloseTo(25);
        expect(await active.locator("span").evaluate((element) => Number.parseFloat(element.style.height))).toBeCloseTo(100);
        await list.getByRole("button", { name: "Ready: 1 unfinished card", exact: true }).hover();
        await expect(page.getByRole("tooltip").locator("[data-workload-pie]")).toBeVisible();
        await expect(page.getByRole("tooltip")).toContainText("Ready");
        await list.getByRole("button", { name: "Active: 4 unfinished cards", exact: true }).focus();
        await expect(page.getByRole("tooltip").last().locator("[data-workload-pie]")).toBeVisible();
        await page.keyboard.press("Escape");
        for (const id of ["favorite-title", "explorer-title"]) {
            expect(await page.getByTestId(id).evaluate((element) => element.getBoundingClientRect().width)).toBeGreaterThan(80);
        }
        const favorites = page.getByRole("region", { name: "Favorites", exact: true });
        if (width < 400) {
            await favorites.getByRole("button", { name: "Unfinished by status", exact: true }).press("Enter");
            await expect(page.getByRole("dialog").locator("[data-workload-pie]")).toBeVisible();
            await expect(page.getByRole("tooltip")).toHaveCount(0);
            await expect(page.getByRole("dialog")).toContainText("Active");
            await page.keyboard.press("Escape");
        } else {
            await favorites.getByRole("button", { name: "Active: 4 unfinished cards", exact: true }).press("Enter");
        }
        await list.getByRole("button", { name: "Active: 4 unfinished cards", exact: true }).press("Enter");
        await expect(page.getByTestId("route")).toContainText("/board/fixture?filters=unfinished%3Ayes%2Ccolumns%3Aactive");
        await page.getByRole("button", { name: "Apply live counts", exact: true }).click();
        await expect(page.getByLabel("30 open cards", { exact: true })).toHaveCount(3);
        await list.getByRole("button", { name: "Ready: 0 unfinished cards", exact: true }).press("Enter");
        await expect(page.getByTestId("route")).toContainText("columns%3Aready");
        expect(await page.locator("button button").count()).toBe(0);
        expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBe(width);
    });
}

for (const [locale, openLabel, statusLabel] of [
    ["en-US", "1,255 open cards", "Ready: 1,234 unfinished cards"],
    ["ko-KR", "열린 카드 1,255개", "Ready: 미완료 카드 1,234개"],
    ["ja-JP", "オープンなカード 1,255 件", "Ready：未完了のカード 1,234 件"],
    ["zh-CN", "1,255 张开放卡片", "Ready：1,234 张未完成卡片"],
]) {
    test(`dashboard counts use locale number interpolation at ${locale}`, async ({ page }) => {
        await page.goto(`/src/pages/DashboardPage/components/workload.fixture.html?lang=${locale}`);
        await page.getByRole("button", { name: "Apply large counts", exact: true }).click();
        await expect(page.getByLabel(openLabel, { exact: true })).toHaveCount(3);
        await expect(page.getByRole("region", { name: "Project count", exact: true })).toContainText("1,002");
        await expect(page.getByRole("region", { name: "Project count", exact: true }).getByRole("button", { name: /1,001/ })).toBeVisible();
        const list = page.getByRole("region", { name: "Project list", exact: true });
        await expect(list.getByRole("button", { name: statusLabel, exact: true })).toBeVisible();
        await list.getByRole("button", { name: statusLabel, exact: true }).hover();
        await expect(page.getByRole("tooltip")).toContainText("1,234");
        await expect(page.getByRole("tooltip").getByRole("img")).toHaveAttribute("aria-label", /1,243/);
    });
}
