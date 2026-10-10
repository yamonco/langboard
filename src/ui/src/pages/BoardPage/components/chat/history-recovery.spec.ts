import { expect, test } from "@playwright/test";
test("failed initial history preserves cached messages and retries with keyboard", async ({ page }) => {
    const errors: string[] = [];
    page.on("pageerror", (error) => errors.push(error.message));
    await page.goto("/src/pages/BoardPage/components/chat/history-recovery.fixture.html");
    await expect(page.getByRole("alert")).toBeVisible();
    await expect(page.getByText("cached", { exact: true })).toBeVisible();
    await page.getByRole("button", { name: "Retry", exact: true }).press("Enter");
    await expect(page.getByRole("alert")).toHaveCount(0);
    await expect(page.getByText("cached", { exact: true })).toBeVisible();
    expect(errors).toEqual([]);
});
test("stale initial failure does not mark a replacement session failed", async ({ page }) => {
    await page.goto("/src/pages/BoardPage/components/chat/history-recovery.fixture.html?stale");
    await expect(page.getByRole("status")).toBeVisible();
    await page.getByRole("button", { name: "Switch session", exact: true }).click();
    await page.getByRole("button", { name: "Reject stale request", exact: true }).click();
    await expect(page.getByRole("alert")).toHaveCount(0);
    await expect(page.getByRole("status")).toHaveCount(0);
});
