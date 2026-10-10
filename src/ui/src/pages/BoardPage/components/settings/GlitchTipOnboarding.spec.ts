import { test, expect } from "@playwright/test";
const path = "/src/pages/BoardPage/components/settings/GlitchTipOnboarding.fixture.html";
for (const width of [1920, 390])
    test(`remove retained selection without provider discovery ${width}`, async ({ page }) => {
        await page.setViewportSize({ width, height: 1000 });
        await page.goto(path + "?selected&deny");
        await page.getByRole("combobox", { name: "Existing connection" }).selectOption("conn");
        await page.getByRole("button", { name: "Load saved selections" }).click();
        await page.getByRole("button", { name: "Remove selection", exact: true }).click();
        await expect(page.getByRole("button", { name: "Remove selection", exact: true })).toHaveCount(0);
        const calls = await page.evaluate(() => (window as unknown as { glitchtipCalls: { url: string }[] }).glitchtipCalls);
        expect(calls.some((row) => row.url.endsWith("/resources"))).toBe(false);
        expect(calls.some((row) => row.url.endsWith("/remove"))).toBe(true);
    });
for (const width of [1920, 390])
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

async function openSelected(page: import("@playwright/test").Page, query = "selected") {
    await page.goto(path + "?" + query);
    await page.getByRole("combobox", { name: "Existing connection" }).selectOption("conn");
    await page.getByRole("button", { name: "Load organizations" }).click();
}
async function issueCalls(page: import("@playwright/test").Page) {
    return page.evaluate(() => (window as unknown as { glitchtipCalls: { method: string; url: string; data: unknown }[] }).glitchtipCalls);
}
test("read consent can be revoked without disconnecting or provider refresh", async ({ page }) => {
    await openSelected(page, "selected&enabled");
    const refresh = page.getByRole("button", { name: "Refresh issue observations", exact: true });
    await expect(refresh).toBeEnabled();
    await page.getByRole("button", { name: "Revoke board read access", exact: true }).click();
    await expect(refresh).toBeDisabled();
    await expect(page.getByRole("button", { name: "Enable read access", exact: true })).toBeVisible();
    const calls = await issueCalls(page);
    expect(calls.find((row) => row.url.endsWith("/disable-read"))?.data).toEqual({
        expected_connection_revision: "a".repeat(64),
        expected_binding_revision: "b".repeat(64),
    });
    expect(calls.some((row) => row.url.endsWith("/disconnect") || row.url.endsWith("/issues/refresh"))).toBe(false);
});
for (const width of [1920, 390])
    test(`explicit consent and safe status observations ${width}`, async ({ page }) => {
        await page.setViewportSize({ width, height: 1080 });
        await openSelected(page, "selected&issuepages");
        const refresh = page.getByRole("button", { name: "Refresh issue observations", exact: true });
        await expect(refresh).toBeDisabled();
        expect((await issueCalls(page)).filter((row) => row.method === "post")).toHaveLength(0);
        await page.getByRole("button", { name: "Enable read access", exact: true }).click();
        await page.getByRole("button", { name: "Cancel", exact: true }).click();
        expect((await issueCalls(page)).filter((row) => row.method === "post")).toHaveLength(0);
        await page.getByRole("button", { name: "Enable read access", exact: true }).click();
        await page.getByRole("button", { name: "Confirm read access", exact: true }).click();
        await expect(refresh).toBeEnabled();
        expect((await issueCalls(page)).find((row) => row.url.endsWith("/read-access"))?.data).toEqual({
            expected_connection_revision: "a".repeat(64),
            expected_binding_revision: "b".repeat(64),
        });
        expect((await issueCalls(page)).filter((row) => row.url.endsWith("/issues/refresh"))).toHaveLength(0);
        await refresh.click();
        await expect(page.getByText("Issue 101 · Observed resolved", { exact: true })).toBeVisible();
        await expect(page.getByText("Issue 102 · Observed unresolved", { exact: true })).toBeVisible();
        await expect(page.getByText("Issue 103 · Observed ignored", { exact: true })).toBeVisible();
        await expect(page.getByText("Observation time is when status was read", { exact: false })).toBeVisible();
        await expect(page.locator("time").first()).toHaveText(
            await page.evaluate(() =>
                new Intl.DateTimeFormat("en-US", { dateStyle: "medium", timeStyle: "medium" }).format(new Date("2026-10-08T10:00:00Z"))
            )
        );
        await expect(page.getByText(/PRIVATE/)).toHaveCount(0);
        expect((await issueCalls(page)).filter((row) => row.url.endsWith("/issues/refresh"))).toHaveLength(1);
        await page.getByRole("button", { name: "More issue observations", exact: true }).click();
        await expect(page.getByText("Issue 101 · Observed unresolved", { exact: true })).toBeVisible();
        await expect(page.getByText("Issue 101 · Observed resolved", { exact: true })).toHaveCount(0);
        expect((await issueCalls(page)).filter((row) => row.url.endsWith("/issues/refresh")).map((row) => row.data)).toEqual([
            { expected_connection_revision: "a".repeat(64), expected_access_revision: 0 },
            { expected_connection_revision: "a".repeat(64), expected_access_revision: 0, cursor: "issue-next" },
        ]);
        expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
        await page.screenshot({ path: `test-results/glitchtip-observation-${width}.png`, fullPage: true });
        await page.getByRole("combobox", { name: "Existing connection" }).selectOption("");
        await expect(page.locator("time")).toHaveCount(0);
    });
for (const query of ["selected&enabled&missingcap", "selected&nobinding", "selected&enabled&revoked"])
    test(`current grants gate issue reads ${query}`, async ({ page }) => {
        await openSelected(page, query);
        const refresh = page.getByRole("button", { name: "Refresh issue observations", exact: true });
        if (query.includes("revoked")) await expect(refresh).toHaveCount(0);
        else await expect(refresh).toBeDisabled();
        expect((await issueCalls(page)).filter((row) => row.method === "post")).toHaveLength(0);
    });
test("empty observations do not imply resolution", async ({ page }) => {
    await openSelected(page, "selected&enabled&empty");
    await page.getByRole("button", { name: "Refresh issue observations", exact: true }).click();
    await expect(page.getByText("No issues observed. This does not mean all issues are resolved.", { exact: true })).toBeVisible();
    await expect(page.locator("time")).toHaveCount(0);
});
for (const query of ["selected&enabled&denyissues", "selected&enabled&wrongresource", "selected&denyconsent"])
    test(`read failure clears observations ${query}`, async ({ page }) => {
        await openSelected(page, query);
        if (query.includes("denyconsent")) {
            await page.getByRole("button", { name: "Enable read access", exact: true }).click();
            await page.getByRole("button", { name: "Confirm read access", exact: true }).click();
        } else await page.getByRole("button", { name: "Refresh issue observations", exact: true }).click();
        await expect(page.getByRole("alert")).toBeVisible();
        await expect(page.locator("time")).toHaveCount(0);
        await expect(page.getByRole("combobox", { name: "Existing connection" })).toHaveValue("");
    });
for (const action of ["consent", "refresh"])
    for (const switchAction of ["Switch board", "Remove permission"])
        test(`scope change suppresses inflight ${action} ${switchAction}`, async ({ page }) => {
            await openSelected(page, action === "consent" ? "selected&delayedconsent" : "selected&enabled&delayedissues");
            if (action === "consent") {
                await page.getByRole("button", { name: "Enable read access", exact: true }).click();
                await page.getByRole("button", { name: "Confirm read access", exact: true }).click();
            } else await page.getByRole("button", { name: "Refresh issue observations", exact: true }).click();
            await expect(page.getByText("Loading...", { exact: true })).toBeVisible();
            await page.getByRole("button", { name: switchAction }).click();
            await page.waitForTimeout(450);
            await expect(page.locator("time")).toHaveCount(0);
            await expect(page.getByText("Board read access enabled.")).toHaveCount(0);
        });

test("resource removal clears prior observations", async ({ page }) => {
    await openSelected(page, "selected&enabled");
    await page.getByRole("button", { name: "Refresh issue observations", exact: true }).click();
    await expect(page.locator("time")).toHaveCount(3);
    await page.getByRole("combobox", { name: "Organization", exact: true }).selectOption("organization");
    await expect(page.locator("time")).toHaveCount(0);
    await page.getByRole("button", { name: "Refresh issue observations", exact: true }).click();
    await expect(page.locator("time")).toHaveCount(3);
    await page.getByRole("checkbox").uncheck();
    await expect(page.locator("time")).toHaveCount(0);
    await expect(page.getByRole("button", { name: "Refresh issue observations", exact: true })).toHaveCount(0);
});
