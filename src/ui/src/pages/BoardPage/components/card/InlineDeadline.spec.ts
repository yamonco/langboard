import { expect, test } from "@playwright/test";
for (const width of [1280, 390]) {
    test(`inline add, change, remove and failure retry at ${width}px`, async ({ page }) => {
        await page.setViewportSize({ width, height: 850 });
        await page.clock.setFixedTime(new Date("2026-10-03T09:00:00Z"));
        page.on("pageerror", (error) => {
            throw error;
        });
        const writes: Record<string, unknown>[] = [];
        let fail = false;
        await page.route("**/board/fixture-board/card/fixture-card/details", async (route) => {
            const headers = {
                "Access-Control-Allow-Origin": "http://127.0.0.1:4204",
                "Access-Control-Allow-Credentials": "true",
                "Access-Control-Allow-Methods": "PUT,OPTIONS",
                "Access-Control-Allow-Headers": "content-type,authorization,content-encoding",
            };
            if (route.request().method() === "OPTIONS") return route.fulfill({ status: 204, headers });
            expect(route.request().method()).toBe("PUT");
            writes.push(route.request().postDataJSON());
            await route.fulfill({
                status: fail ? 500 : 200,
                contentType: "application/json",
                headers,
                body: fail ? JSON.stringify({ detail: "Save failed" }) : "{}",
            });
        });
        await page.goto("/src/pages/BoardPage/components/card/inline-deadline.fixture.html");
        await page.getByRole("button", { name: "Add deadline", exact: true }).press("Enter");
        await page.getByRole("button", { name: "Done", exact: true }).click();
        await expect(page.locator("output")).not.toHaveText("empty");
        expect(Object.keys(writes[0])).toEqual(["deadline_at"]);
        const original = await page.locator("output").innerText();
        await page.getByRole("button", { name: "Set deadline", exact: true }).click();
        // Choose a future day in the current calendar month.
        const days = page.getByRole("gridcell").getByRole("button");
        const enabled = await days.all();
        let chosen = false;
        for (const day of enabled.reverse()) {
            if (await day.isEnabled()) {
                await day.click();
                chosen = true;
                break;
            }
        }
        expect(chosen).toBe(true);
        await page.getByRole("button", { name: "Done", exact: true }).click();
        await expect(page.locator("output")).not.toHaveText(original);
        fail = true;
        const confirmed = await page.locator("output").innerText();
        await page.getByRole("button", { name: "Remove deadline", exact: true }).click();
        await expect(page.getByRole("button", { name: "Remove deadline", exact: true })).toBeEnabled();
        await expect(page.locator("output")).toHaveText(confirmed);
        fail = false;
        await page.getByRole("button", { name: "Remove deadline", exact: true }).click();
        await expect(page.locator("output")).toHaveText("empty");
        expect(writes.at(-1)).toEqual({ deadline_at: "" });
        expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    });
}
test("reader cannot mutate a deadline", async ({ page }) => {
    let writes = 0;
    await page.route("**/board/fixture-board/card/fixture-card/details", async (route) => {
        if (route.request().method() === "PUT") writes++;
        await route.fulfill({ status: 403, json: { code: "PE1001" } });
    });
    page.on("pageerror", (error) => {
        throw error;
    });
    await page.goto("/src/pages/BoardPage/components/card/inline-deadline.fixture.html?readonly&existing");
    await expect(page.getByRole("button", { name: "Set deadline", exact: true })).toBeDisabled();
    await expect(page.getByRole("button", { name: "Remove deadline", exact: true })).toHaveCount(0);
    await page.goto("/src/pages/BoardPage/components/card/inline-deadline.fixture.html?readonly");
    await expect(page.getByRole("button", { name: "Add deadline", exact: true })).toHaveCount(0);
    expect(writes).toBe(0);
});
