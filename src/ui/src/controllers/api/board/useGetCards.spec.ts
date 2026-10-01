import { expect, test } from "@playwright/test";

const fixture = "/src/controllers/api/board/useGetCards.fixture.html";
test("slow and failed enrichment cannot block board data; refresh recovers only current-card metadata", async ({ page }) => {
    await page.goto(fixture);
    await expect(page.getByRole("heading", { name: "Board ready" })).toBeVisible();
    await expect(page.getByText("Authorized card", { exact: true })).toBeVisible();
    await expect(page.getByText("Metadata entries: 0")).toBeVisible();
    await expect(page.locator("li")).toHaveCount(2);
    await page.getByRole("button", { name: "Reject metadata" }).click();
    await expect(page.getByRole("heading", { name: "Board ready" })).toBeVisible();
    await page.getByRole("button", { name: "Refresh board" }).click();
    await expect(page.getByText("Metadata entries: 1")).toBeVisible();
    await expect(page.locator("li")).toHaveCount(4);
});
test("a denied primary snapshot never loads enrichment or displays a card", async ({ page }) => {
    await page.goto(fixture + "?deny=1");
    await expect(page.getByRole("heading", { name: "Board denied" })).toBeVisible();
    await expect(page.getByText("Authorized card", { exact: true })).toHaveCount(0);
    await expect(page.getByText("Metadata entries: 0")).toBeVisible();
    await expect(page.locator("li")).toHaveCount(1);
});

test("a new observer after failure enriches only its fresh snapshot", async ({ page }) => {
    await page.goto(fixture);
    await expect(page.locator("li")).toHaveCount(2);
    await page.getByRole("button", { name: "Reject metadata" }).click();
    await page.getByRole("button", { name: "Enable second observer" }).click();
    await expect(page.locator("li")).toHaveCount(4);
    await page.getByRole("button", { name: "Release metadata" }).click();
    await expect(page.getByText("Metadata value: loaded-2")).toBeVisible();
});
test("a replaced snapshot aborts late enrichment instead of overwriting fresh metadata", async ({ page }) => {
    await page.goto(fixture);
    await expect(page.locator("li")).toHaveCount(2);
    await page.getByRole("button", { name: "Refresh board" }).click();
    await expect(page.getByText("Metadata value: loaded-2")).toBeVisible();
    await expect(page.getByText("Aborted metadata: 1")).toBeVisible();
    await page.getByRole("button", { name: "Release metadata" }).click();
    await expect(page.getByText("Metadata value: loaded-2")).toBeVisible();
    await expect(page.locator("li")).toHaveCount(4);
});
