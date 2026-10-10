import { expect, test } from "@playwright/test";
for (const width of [1280, 700, 390]) {
    test(`recent views keep projects accessible at ${width}px`, async ({ page }) => {
        await page.setViewportSize({ width, height: 844 });
        await page.goto("/src/pages/DashboardPage/components/recent-cards.fixture.html");
        const recent = page.getByRole("region", { name: "Recent cards", exact: true });
        await expect(recent.getByRole("button", { name: /^Card \d+$/ })).toHaveCount(10);
        await expect(recent.getByRole("button", { name: "Card 0", exact: true })).toHaveCount(0);
        const projects = page.locator("[data-explorer-project-list]");
        const measure = () => projects.evaluate((e) => ({ height: e.clientHeight, bottom: e.getBoundingClientRect().bottom }));
        expect((await measure()).height).toBeGreaterThanOrEqual(96);
        expect((await measure()).bottom).toBeLessThanOrEqual(844);
        await recent.getByRole("button", { name: "Show older cards (4)", exact: true }).press("Enter");
        await expect(recent.getByRole("button", { name: /^Card \d+$/ })).toHaveCount(14);
        expect((await measure()).height).toBeGreaterThanOrEqual(96);
        await recent.getByRole("button", { name: "Card 0", exact: true }).click();
        await expect(page.getByTestId("route")).toHaveText("/board/fixture/0");
        await page.getByRole("button", { name: "Read oldest again", exact: true }).click();
        await recent.getByRole("button", { name: "Show fewer cards", exact: true }).click();
        await expect(recent.getByRole("button", { name: /^Card \d+$/ })).toHaveCount(10);
        await expect(recent.getByRole("button", { name: /^Card \d+$/ }).first()).toHaveText("Card 0");
        expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBe(width);
        expect(await page.locator("button button").count()).toBe(0);
        await page.goto("/src/pages/DashboardPage/components/recent-cards.fixture.html?count=10");
        await expect(recent.getByRole("button", { name: /Show older|Show fewer/ })).toHaveCount(0);
        await expect(recent.getByRole("button", { name: /^Card \d+$/ })).toHaveCount(10);
    });
}

test("offline deletion and permission loss remove only confirmed unavailable history", async ({ page }) => {
    let status = 200;
    let calls = 0;
    await page.route("**/board/fixture/cards/available", async (route) => {
        if (route.request().method() === "OPTIONS") {
            await route.fulfill({
                status: 204,
                headers: {
                    "Access-Control-Allow-Origin": "http://127.0.0.1:4188",
                    "Access-Control-Allow-Credentials": "true",
                    "Access-Control-Allow-Methods": "POST, OPTIONS",
                    "Access-Control-Allow-Headers": "content-type, content-encoding, authorization",
                },
            });
            return;
        }
        calls++;
        const uids = route.request().postDataJSON().card_uids as string[];
        await route.fulfill({
            status,
            headers: { "Access-Control-Allow-Origin": "http://127.0.0.1:4188", "Access-Control-Allow-Credentials": "true" },
            contentType: "application/json",
            body: JSON.stringify({ card_uids: uids.filter((uid) => uid !== "13") }),
        });
    });
    await page.goto("/src/pages/DashboardPage/components/recent-cards.fixture.html");
    const recent = page.getByRole("region", { name: "Recent cards", exact: true });
    await expect.poll(() => calls).toBeGreaterThan(0);
    await expect(recent.getByRole("button", { name: "Card 13", exact: true })).toHaveCount(0);
    await expect(recent.getByRole("button", { name: "Card 12", exact: true })).toBeVisible();
    await expect(recent.getByRole("button", { name: "Show older cards (3)", exact: true })).toBeVisible();
    status = 503;
    const previous = calls;
    await page.evaluate(() => window.dispatchEvent(new Event("focus")));
    await expect.poll(() => calls).toBeGreaterThan(previous);
    await expect(recent.getByRole("button", { name: "Card 12", exact: true })).toBeVisible();
    status = 403;
    await page.evaluate(() => window.dispatchEvent(new Event("focus")));
    await expect(recent.getByRole("button", { name: /^Card \d+$/ })).toHaveCount(0);
});

test("online recovery prunes inaccessible cards while preserving pins and close actions", async ({ page }) => {
    let available = false;
    let calls = 0;
    await page.route("**/board/fixture/cards/available", async (route) => {
        const headers = {
            "Access-Control-Allow-Origin": "http://127.0.0.1:4188",
            "Access-Control-Allow-Credentials": "true",
            "Access-Control-Allow-Methods": "POST, OPTIONS",
            "Access-Control-Allow-Headers": "content-type, content-encoding, authorization",
        };
        if (route.request().method() === "OPTIONS") {
            await route.fulfill({ status: 204, headers });
            return;
        }
        calls++;
        const uids = route.request().postDataJSON().card_uids as string[];
        await route.fulfill({
            status: available ? 200 : 503,
            headers,
            contentType: "application/json",
            body: JSON.stringify({ card_uids: uids.filter((uid) => uid !== "13") }),
        });
    });
    await page.goto("/src/pages/DashboardPage/components/recent-cards.fixture.html");
    const recent = page.getByRole("region", { name: "Recent cards", exact: true });
    await expect.poll(() => calls).toBeGreaterThan(0);
    await expect(recent.getByRole("button", { name: "Card 13", exact: true })).toBeVisible();
    available = true;
    const previous = calls;
    await page.evaluate(() => window.dispatchEvent(new Event("online")));
    await expect.poll(() => calls).toBeGreaterThan(previous);
    await expect(recent.getByRole("button", { name: "Card 13", exact: true })).toHaveCount(0);
    await expect(recent.getByRole("button", { name: "Card 12", exact: true })).toBeVisible();
    await recent.getByRole("button", { name: "Show older cards (3)", exact: true }).click();
    const oldest = recent.locator(".group").filter({ has: page.getByRole("button", { name: "Card 0", exact: true }) });
    await expect(oldest.getByRole("button", { name: "Unpin card", exact: true })).toBeVisible();
    await oldest.getByRole("button", { name: "Unpin card", exact: true }).click();
    await expect(oldest.getByRole("button", { name: "Pin card", exact: true })).toBeVisible();
    await oldest.getByRole("button", { name: "Pin card", exact: true }).click();
    await oldest.getByRole("button", { name: "Close card from list", exact: true }).click();
    await expect(recent.getByRole("button", { name: "Card 0", exact: true })).toHaveCount(0);
    await expect(recent.getByRole("button", { name: /^Card \d+$/ })).toHaveCount(12);
});
