import { test, expect } from "@playwright/test";

for (const width of [1280, 390]) {
    test(`table row controls remain available for single cell text at ${width}px`, async ({ page }) => {
        await page.setViewportSize({ width, height: 900 });
        const errors: string[] = [];
        page.on("pageerror", (error) => errors.push(error.message));
        await page.goto("/src/components/Editor/table-selection.fixture.html");
        await page.getByRole("button", { name: "Select single cell text" }).click();
        await expect(page.getByRole("button", { name: "editor.Insert row after", exact: true })).toBeVisible();
        await page.getByRole("button", { name: "editor.Insert row after", exact: true }).click();
        await expect(page.locator("table tr")).toHaveCount(2);
        await page.getByRole("button", { name: "Select multiple cells" }).click();
        await expect(page.getByRole("button", { name: "editor.Insert row after", exact: true })).toHaveCount(0);
        expect(errors).toEqual([]);
    });
}
