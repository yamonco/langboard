import { expect, test } from "@playwright/test";
test("authenticated bootstrap loads notifications once through the header", async ({ page }) => {
    await page.goto("/src/core/providers/NotificationLoad.fixture.html");
    await expect(page.locator("#state")).toHaveText("loaded");
    await expect(page.locator("#reads")).toHaveText("1");
});
