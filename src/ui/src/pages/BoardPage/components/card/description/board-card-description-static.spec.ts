import { test, expect } from "@playwright/test";

test("static description chunks render internal links without runtime Plate hooks", async ({ page }, testInfo) => {
    const pageErrors: string[] = [];
    page.on("pageerror", (error) => pageErrors.push(error.message));

    await page.goto("/src/pages/BoardPage/components/card/description/board-card-description-static.fixture.html");
    await expect(page.locator("[data-card-description-chunk]")).toBeVisible();
    await expect(page.locator(".internal-link")).toHaveText(/fixture-card/);
    await expect(page.locator("a").filter({ hasText: "https://example.com/fixture" })).toBeVisible();
    await page.waitForTimeout(250);

    expect(pageErrors).not.toContain("Plate hooks must be used inside a Plate or PlateController");
    expect(pageErrors).toEqual([]);
    await page.screenshot({ path: testInfo.outputPath("static-description.png") });
});
