import { test, expect } from "@playwright/test";
const path = "/src/pages/BoardPage/components/settings/GlitchTipOnboarding.fixture.html";
for (const width of [1440, 390])
    test(`register and select/remove without token transport ${width}`, async ({ page }) => {
        await page.setViewportSize({ width, height: 1000 });
        await page.goto(path + "?new");
        await page.getByLabel("Instance URL", { exact: true }).fill("https://errors.example.invalid");
        await page.getByRole("button", { name: "Store API token securely" }).click();
        await expect(page.getByRole("link", { name: "Open secure token input" })).toHaveAttribute("href", /\/secret-input\/s{43}$/);
        await page.getByRole("button", { name: "Check token input" }).click();
        await expect(page.getByLabel("API credential reference")).toHaveValue("secret://ref/abcdefghijk");
        await page.getByRole("button", { name: "Connect", exact: true }).click();
        await page.getByRole("button", { name: "Load organizations" }).click();
        await page.getByRole("combobox", { name: "Organization", exact: true }).selectOption("organization");
        const checkbox = page.getByRole("checkbox");
        await checkbox.check();
        await expect(checkbox).toBeChecked();
        await checkbox.uncheck();
        await expect(checkbox).not.toBeChecked();
        await checkbox.check();
        const calls = await page.evaluate(
            () => (window as unknown as { glitchtipCalls: { method: string; url: string; data: unknown }[] }).glitchtipCalls
        );
        const registration = calls.find((row) => row.method === "post" && row.url.endsWith("/connections"));
        expect(registration?.data).toEqual({ instance_url: "https://errors.example.invalid", credential_reference: "secret://ref/abcdefghijk" });
        const writes = calls.filter((row) => row.method === "post" && row.url.endsWith("/projects"));
        expect(writes[0].data).toMatchObject({ expected_resource_revision: null, expected_revision: "a".repeat(64) });
        expect(writes[1].data).toMatchObject({ expected_resource_revision: 2 });
        expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
        await page.screenshot({ path: `test-results/glitchtip-onboarding-${width}.png`, fullPage: true });
        await page.getByRole("button", { name: "Disconnect", exact: true }).click();
        await expect(page.getByText("Disconnect external access on every board.", { exact: false })).toBeVisible();
        await page.getByRole("button", { name: "Confirm disconnect" }).click();
        await expect(page.getByRole("button", { name: "Connect", exact: true })).toBeVisible();
    });

test("readonly sends no connection/credential requests", async ({ page }) => {
    await page.goto(path + "?readonly");
    await expect(page.getByRole("button", { name: "Store API token securely" })).toBeDisabled();
    expect(await page.evaluate(() => (window as unknown as { glitchtipCalls: unknown[] }).glitchtipCalls.length)).toBe(0);
});

test("denial clears prior connection and resource display", async ({ page }) => {
    await page.goto(path + "?deny");
    await page.getByRole("combobox", { name: "Existing connection" }).selectOption("conn");
    await page.getByRole("button", { name: "Load organizations" }).click();
    await expect(page.getByRole("alert")).toBeVisible();
    await expect(page.getByRole("combobox", { name: "Existing connection" })).toHaveValue("");
    await expect(page.getByRole("checkbox")).toHaveCount(0);
});

test("project pagination stays in the selected organization", async ({ page }) => {
    await page.goto(path + "?pages");
    await page.getByRole("combobox", { name: "Existing connection" }).selectOption("conn");
    await page.getByRole("button", { name: "Load organizations" }).click();
    await page.getByRole("combobox", { name: "Organization", exact: true }).selectOption("organization");
    await page.getByRole("button", { name: "More projects" }).click();
    await expect(page.getByRole("checkbox")).toHaveCount(2);
    const calls = await page.evaluate(() => (window as unknown as { glitchtipCalls: { params: unknown }[] }).glitchtipCalls);
    expect(calls.at(-1)?.params).toEqual({ organization: "organization", cursor: "next" });
});

test("board switch discards an in-flight old resource response", async ({ page }) => {
    await page.goto(path + "?delayed");
    await page.getByRole("combobox", { name: "Existing connection" }).selectOption("conn");
    await page.getByRole("button", { name: "Load organizations" }).click();
    await expect(page.getByRole("status")).toBeVisible();
    await page.getByRole("button", { name: "Switch board" }).click();
    await expect(page.getByRole("combobox", { name: "Existing connection" })).toHaveValue("");
    await expect(page.getByRole("status")).toHaveCount(0);
    await page.waitForTimeout(450);
    await expect(page.getByRole("combobox", { name: "Organization", exact: true })).toHaveCount(0);
    const calls = await page.evaluate(() => (window as unknown as { glitchtipCalls: { url: string }[] }).glitchtipCalls);
    expect(calls.some((row) => row.url === "/board/fixture/settings/apps/glitchtip/connections/conn/projects")).toBe(false);
});
