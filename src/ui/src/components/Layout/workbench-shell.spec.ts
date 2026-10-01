import { expect, test } from "@playwright/test";

test("route changes retain the physical shell and preserve page context in its sidebar", async ({ page }) => {
    await page.goto("/src/components/Layout/workbench-shell.fixture.html");
    await expect(page.getByRole("heading", { name: "Dashboard", exact: true })).toBeVisible();
    // Browser-owned references detect replacement even when the new DOM looks identical.
    const nodes = await Promise.all([
        page.locator("header").elementHandle(),
        page.getByRole("navigation", { name: "Workspace", exact: true }).elementHandle(),
        page.locator("aside").elementHandle(),
    ]);
    for (const name of ["Board", "Card", "Wiki", "Dashboard"]) {
        await page.getByRole("link", { name: `Open ${name}`, exact: true }).click();
        await expect(page.getByRole("heading", { name, exact: true })).toBeVisible();
        await expect(page.getByText(`Sidebar ${name}`, { exact: true })).toBeVisible();
        for (const node of nodes) expect(await node!.evaluate((element) => element.isConnected)).toBe(true);
        await expect(page.locator("[inert]")).toHaveCount(0);
    }
    const home = page.getByRole("link", { name: "Go to Dashboard", exact: true });
    await expect(home).toHaveAttribute("href", "/dashboard/projects/all");
    await home.focus();
    await expect(home).toBeFocused();
    await home.press("Enter");
    await expect(page.getByRole("heading", { name: "Dashboard", exact: true })).toBeVisible();
});

test("mobile drawer actions are keyboard reachable and open context content", async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await page.goto("/src/components/Layout/workbench-shell.fixture.html");
    await page.getByRole("button", { name: "Toggle navigation menu", exact: true }).click();
    const explorer = page.getByRole("button", { name: "Explorer", exact: true });
    await explorer.focus();
    await explorer.press("Enter");
    await expect(page.getByText("Sidebar Dashboard", { exact: true })).toBeVisible();
    await page.getByRole("button", { name: "Close", exact: true }).click();
    await expect(page.getByText("Sidebar Dashboard", { exact: true })).toHaveCount(0);
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBe(390);
});

// Initial page registration must not move the outlet into a new React subtree.
test("initial shell registration mounts the page once", async ({ page }) => {
    await page.goto("/src/components/Layout/workbench-shell.fixture.html");
    await expect(page.getByRole("heading", { name: "Dashboard", exact: true })).toBeVisible();
    await expect(page.getByTestId("page-mounts")).toHaveText("1");
});
