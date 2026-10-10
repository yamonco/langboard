import { expect, test } from "@playwright/test";
const path = "/src/controllers/api/board/useGetProject.fixture.html";
test("cards load while dock is pending and late dock applies", async ({ page }) => {
    await page.goto(path);
    await expect(page.getByText("Cards ready", { exact: true })).toBeVisible();
    await expect(page.getByText("Dock revision: 0", { exact: true })).toBeVisible();
    await page.getByRole("button", { name: "Release dock" }).click();
    await expect(page.getByText("Dock revision: 1", { exact: true })).toBeVisible();
});
test("dock failure preserves board and explicit project refresh recovers", async ({ page }) => {
    await page.goto(path);
    await expect(page.getByText("Cards ready", { exact: true })).toBeVisible();
    await page.getByRole("button", { name: "Reject dock" }).click();
    await expect(page.getByRole("heading", { name: "Project ready" })).toBeVisible();
    await page.getByRole("button", { name: "Refresh project" }).click();
    await expect(page.locator("li").filter({ hasText: /\/dock$/ })).toHaveCount(2);
    await page.getByRole("button", { name: "Release dock" }).click();
    await expect(page.getByText("Dock revision: 1", { exact: true })).toBeVisible();
});
test("denied project never reads dock or cards", async ({ page }) => {
    await page.goto(`${path}?deny`);
    await expect(page.getByRole("heading", { name: "Project denied" })).toBeVisible();
    await expect(page.locator("li")).toHaveCount(1);
    await expect(page.getByText("Cards ready", { exact: true })).toHaveCount(0);
});
