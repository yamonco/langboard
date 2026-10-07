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

test("mobile mode selection enters the panel, and explicit dismissal restores navigation focus", async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await page.goto("/src/components/Layout/workbench-shell.fixture.html");
    const trigger = page.getByRole("button", { name: "Toggle navigation menu", exact: true });
    await trigger.press("Enter");
    await page.getByRole("dialog").getByRole("button", { name: "Explorer", exact: true }).press("Enter");
    const panel = page.getByRole("complementary", { name: "Explorer", exact: true });
    await expect(panel).toBeFocused();
    await panel.press("Tab");
    const close = panel.getByRole("button", { name: "Close", exact: true });
    await expect(close).toBeFocused();
    await close.press("Escape");
    await expect(panel).toHaveCount(0);
    await expect(trigger).toBeFocused();
    await trigger.press("Enter");
    await page.getByRole("dialog").getByRole("button", { name: "Explorer", exact: true }).press("Enter");
    await expect(panel).toBeFocused();
    await panel.press("Tab");
    await close.press("Enter");
    await expect(panel).toHaveCount(0);
    await expect(trigger).toBeFocused();
    // Cancelling the navigation drawer keeps normal trigger restoration.
    await trigger.press("Enter");
    await page.getByRole("dialog").press("Escape");
    await expect(trigger).toBeFocused();
});

test("a nested mobile menu owns Escape before the context panel", async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await page.goto("/src/components/Layout/workbench-shell.fixture.html");
    await page.getByRole("button", { name: "Toggle navigation menu", exact: true }).press("Enter");
    await page.getByRole("dialog").getByRole("button", { name: "Explorer", exact: true }).press("Enter");
    const panel = page.getByRole("complementary", { name: "Explorer", exact: true });
    await expect(panel).toBeFocused();
    await panel.getByRole("button", { name: "Nested menu", exact: true }).press("Enter");
    await expect(page.getByRole("menuitem", { name: "Nested item", exact: true })).toBeVisible();
    await page.getByRole("menuitem", { name: "Nested item", exact: true }).press("Escape");
    await expect(page.getByRole("menu")).toHaveCount(0);
    await expect(panel).toBeVisible();
    await expect(panel.getByRole("button", { name: "Nested menu", exact: true })).toBeFocused();
});

test("project navigation focuses the existing palette trigger after the new configuration is ready", async ({ page }) => {
    await page.goto("/src/components/Layout/workbench-shell.fixture.html");
    await page.getByRole("link", { name: "Open Board", exact: true }).press("Enter");
    await expect(page.getByRole("heading", { name: "Board", exact: true })).toBeVisible();
    await expect(page.getByRole("button", { name: "Command palette", exact: true })).toBeFocused();
});

test("Escape from page-owned portaled controls dismisses the physical mobile panel", async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await page.goto("/src/components/Layout/workbench-shell.fixture.html");
    const trigger = page.getByRole("button", { name: "Toggle navigation menu", exact: true });
    await trigger.press("Enter");
    await page.getByRole("dialog").getByRole("button", { name: "Explorer", exact: true }).press("Enter");
    await expect(page.getByRole("dialog")).toHaveCount(0);
    const panel = page.getByRole("complementary", { name: "Explorer", exact: true });
    await expect(panel).toBeFocused();
    await panel.press("Tab");
    await expect(panel.getByRole("button", { name: "Close", exact: true })).toBeFocused();
    await page.keyboard.press("Tab");
    await expect(panel.getByRole("textbox", { name: "Sidebar search", exact: true })).toBeFocused();
    await page.keyboard.press("Tab");
    await expect(panel.getByRole("button", { name: "Nested menu", exact: true })).toBeFocused();
    await page.keyboard.press("Escape");
    await expect(panel).toHaveCount(0);
    await expect(trigger).toBeFocused();
    await expect(page.getByRole("heading", { name: "Dashboard", exact: true })).toBeVisible();
});

test("same workspace navigation preserves sidebar state", async ({ page }) => {
    await page.goto("/src/components/Layout/workbench-shell.fixture.html");
    await page.getByRole("link", { name: "Open Board", exact: true }).click();
    await page.getByRole("textbox", { name: "Sidebar search", exact: true }).fill("retained query");
    await page.getByRole("link", { name: "Open Card", exact: true }).click();
    await expect(page.getByRole("heading", { name: "Card", exact: true })).toBeVisible();
    await expect(page.getByRole("textbox", { name: "Sidebar search", exact: true })).toHaveValue("retained query");
    await expect(page.locator("[inert]")).toHaveCount(0);
});

test("split-window Explorer collapses automatically and can be expanded or collapsed explicitly", async ({ page }) => {
    await page.setViewportSize({ width: 1100, height: 800 });
    await page.goto("/src/components/Layout/workbench-shell.fixture.html");
    const sidebar = page.locator("[id^='resizable-sidebar-']").filter({ has: page.getByText("Sidebar Dashboard", { exact: true }) });
    await expect(sidebar).toHaveAttribute("data-collapsed", "true");
    await expect.poll(() => sidebar.evaluate((element) => element.getBoundingClientRect().width)).toBe(52);
    const toggle = sidebar.getByRole("button").last();
    await toggle.click();
    await expect(sidebar).toHaveAttribute("data-collapsed", "false");
    await expect(page.getByText("Sidebar Dashboard", { exact: true })).toBeVisible();
    const bounds = await toggle.boundingBox();
    expect(bounds!.x).toBeGreaterThanOrEqual(0);
    expect(bounds!.x + bounds!.width).toBeLessThanOrEqual(1100);
    await toggle.click();
    await expect(sidebar).toHaveAttribute("data-collapsed", "true");
    await toggle.click();
    await expect(sidebar).toHaveAttribute("data-collapsed", "false");
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBe(1100);
});

test("comment layout follows card width even within a wide viewport and reserves action space", async ({ page }) => {
    await page.setViewportSize({ width: 1400, height: 900 });
    await page.goto("/src/pages/BoardPage/components/card/card-comment-layout.fixture.html");
    const mode = page.getByTestId("comment-layout");
    await expect(mode).toHaveText("mobile");
    await page.getByRole("button", { name: "Wide card" }).click();
    await expect(mode).toHaveText("panel");
    await page.getByRole("button", { name: "Toggle actions" }).click();
    await expect(mode).toHaveText("mobile");
    await page.getByRole("button", { name: "Toggle actions" }).click();
    await expect(mode).toHaveText("panel");
    await page.getByRole("button", { name: "Narrow card" }).click();
    await expect(mode).toHaveText("mobile");
});

test("description markers remain within the card viewport and track its internal scroll", async ({ page }) => {
    await page.goto("/src/pages/BoardPage/components/card/description/description-scroll.fixture.html");
    const viewport = page.locator("[data-card-content-viewport]");
    const markers = page.getByRole("button", { name: /Go to description|번째 설명으로 이동/ });
    await expect(markers).toHaveCount(60);
    const first = markers.first();
    const bounds = await viewport.boundingBox();
    const initial = await first.boundingBox();
    expect(initial!.y).toBeGreaterThanOrEqual(bounds!.y);
    expect(initial!.y + initial!.height).toBeLessThanOrEqual(bounds!.y + bounds!.height);
    await viewport.focus();
    await viewport.press("PageDown");
    await viewport.press("PageDown");
    await expect
        .poll(async () => page.locator("button[aria-current='location']").getAttribute("aria-label"))
        .not.toBe(await first.getAttribute("aria-label"));
    await markers.nth(35).click();
    await expect
        .poll(() => page.locator("button[aria-current='location']").getAttribute("aria-label"))
        .toBe(await markers.nth(35).getAttribute("aria-label"));
    await page.getByRole("button", { name: "Resize card" }).click();
    await page.getByRole("button", { name: "Expand header" }).click();
    await markers.first().click();
    await expect(first).toHaveAttribute("aria-current", "location");
    const rail = page.locator("[data-card-description-rail]");
    const beforeEnd = await rail.boundingBox();
    await markers.last().click();
    await expect
        .poll(async () => {
            const current = await rail.boundingBox();
            return !!current && Math.abs(current.y - beforeEnd!.y) < 1 && Math.abs(current.height - beforeEnd!.height) < 1;
        })
        .toBe(true);
    await expect(viewport).toHaveCSS("scrollbar-width", "none");
    await expect
        .poll(async () => {
            const viewportBounds = await viewport.boundingBox();
            const railBounds = await page.locator("[data-card-description-rail]").boundingBox();
            return (
                !!viewportBounds &&
                !!railBounds &&
                railBounds.y >= viewportBounds.y &&
                railBounds.y + railBounds.height <= viewportBounds.y + viewportBounds.height
            );
        })
        .toBe(true);
    await page.getByRole("button", { name: "Short description" }).click();
    await expect(markers).toHaveCount(2);
    await markers.last().click();
    await expect(markers.last()).toHaveAttribute("aria-current", "location");
});

test("expanded Explorer suppresses Activity Rail tooltip and collapsed Explorer restores it", async ({ page }) => {
    const warnings: string[] = [];
    page.on("console", (message) => {
        if (message.type() === "warning") warnings.push(message.text());
    });
    await page.goto("/src/components/Layout/workbench-shell.fixture.html");
    const explorer = page.getByRole("button", { name: "Explorer", exact: true });
    await explorer.focus();
    await expect(page.getByRole("tooltip")).toHaveCount(0);
    await page.getByRole("button", { name: "Collapse", exact: true }).click();
    await page.getByRole("button", { name: "Expand", exact: true }).focus();
    const rail = page.getByRole("navigation", { name: "Workspace", exact: true });
    if (await rail.count()) await expect(rail).toHaveAttribute("data-context-expanded", "false");
    await explorer.focus();
    await expect(page.getByRole("tooltip")).toBeVisible();
    await expect(page.getByRole("tooltip")).toHaveText("Explorer");
    await page.getByRole("button", { name: "Expand", exact: true }).click();
    await explorer.focus();
    await expect(page.getByRole("tooltip")).toHaveCount(0);
    expect(warnings.filter((message) => message.includes("controlled to uncontrolled") || message.includes("uncontrolled to controlled"))).toEqual(
        []
    );
});

test("common Sidebar tooltips follow explicit collapse state", async ({ page }) => {
    const warnings: string[] = [];
    page.on("console", (message) => {
        if (message.type() === "warning") warnings.push(message.text());
    });
    await page.goto("/src/components/Layout/sidebar-tooltip.fixture.html");
    const explorer = page.getByRole("link", { name: "Explorer", exact: true });
    await explorer.focus();
    await expect(page.getByRole("tooltip")).toHaveCount(0);
    await page.getByRole("button", { name: "Collapse", exact: true }).click();
    await page.getByRole("button", { name: "Expand", exact: true }).focus();
    const rail = page.getByRole("navigation", { name: "Workspace", exact: true });
    if (await rail.count()) await expect(rail).toHaveAttribute("data-context-expanded", "false");
    await explorer.focus();
    await expect(page.getByRole("tooltip")).toBeVisible();
    await expect(page.getByRole("tooltip")).toHaveText("Explorer");
    await explorer.click();
    await expect(page).toHaveURL(/#explorer$/);
    await page.getByRole("button", { name: "Expand", exact: true }).click();
    await explorer.focus();
    await expect(page.getByRole("tooltip")).toHaveCount(0);
    expect(warnings.filter((message) => message.includes("controlled to uncontrolled") || message.includes("uncontrolled to controlled"))).toEqual(
        []
    );
});

test("mobile floating Sidebar retains tooltip and link navigation", async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await page.goto("/src/components/Layout/sidebar-tooltip.fixture.html");
    const floating = page.locator(".floating-wrapper");
    await floating.locator("button svg").click();
    const explorer = floating.getByRole("link", { name: "Explorer", exact: true });
    await expect(explorer).toBeVisible();
    await explorer.focus();
    await expect(page.getByRole("tooltip")).toBeVisible();
    await expect(page.getByRole("tooltip")).toHaveText("Explorer");
    await explorer.click();
    await expect(page).toHaveURL(/#explorer$/);
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBe(390);
});

test("failed board list exposes retry and suppresses endless skeletons", async ({ page }) => {
    await page.goto("/src/pages/BoardPage/board-load.fixture.html");
    await expect(page.getByRole("alert")).toBeVisible();
    await expect(page.locator(".animate-pulse")).toHaveCount(0);
    const retry = page.getByRole("button", { name: /Retry|다시 시도/ });
    await retry.press("Enter");
    await expect(page.locator("output")).toHaveText("2");
    await expect(retry).toHaveCount(0);
    await expect(page.locator("output")).toHaveText("2");
    await page.getByRole("button", { name: "Release retry" }).click();
    await expect(retry).toBeEnabled();
    await expect(page.getByRole("alert")).toBeVisible();
    await expect(page.locator(".animate-pulse")).toHaveCount(0);
});

test("mobile description navigator fills a fixed viewport while keyboard scrolling remains available", async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await page.goto("/src/pages/BoardPage/components/card/description/description-scroll.fixture.html");
    const viewport = page.locator("[data-card-content-viewport]");
    const rail = page.locator("[data-card-description-rail]");
    const markers = rail.getByRole("button");
    await expect(markers).toHaveCount(60);
    await expect(rail).toBeVisible();
    const initial = await rail.boundingBox();
    await viewport.focus();
    await viewport.press("PageDown");
    await expect.poll(() => viewport.evaluate((element) => element.scrollTop)).toBeGreaterThan(0);
    await markers.last().click();
    await expect
        .poll(async () => {
            const current = await rail.boundingBox();
            return !!current && Math.abs(current.y - initial!.y) < 1 && Math.abs(current.height - initial!.height) < 1;
        })
        .toBe(true);
    const bounds = await viewport.boundingBox();
    expect(initial!.height).toBeGreaterThan(bounds!.height - 20);
    await expect(viewport).toHaveCSS("scrollbar-width", "none");
});
