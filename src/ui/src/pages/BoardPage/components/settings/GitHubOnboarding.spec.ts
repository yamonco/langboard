import { test, expect } from "@playwright/test";
const path = "/src/pages/BoardPage/components/settings/GitHubOnboarding.fixture.html?code=" + "a".repeat(40) + "&state=" + "s".repeat(43);
for (const width of [1440, 390])
    test(`repository delta and callback cleanup ${width}`, async ({ page }) => {
        await page.setViewportSize({ width, height: 850 });
        await page.goto(path);
        await page.getByRole("button", { name: "example · Organization" }).click();
        await page.getByRole("checkbox", { name: "example/frontend" }).uncheck();
        await page.getByRole("checkbox", { name: "example/backend" }).check();
        await page.getByRole("button", { name: "Save repository selection" }).click();
        await expect(page.getByRole("status")).toContainText("Repository selection saved");
        expect(page.url()).not.toContain("code=");
        expect(page.url()).not.toContain("state=");
        const calls = await page.evaluate(() => (window as unknown as { githubCalls: { method: string; data: unknown }[] }).githubCalls);
        expect(calls.filter((call) => call.method === "put")[0].data).toMatchObject({
            add: [100],
            remove: [99],
            installation_proof: "p".repeat(43),
            expected_revision: "a".repeat(64),
        });
        expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
        await page.screenshot({ path: `test-results/github-onboarding-${width}.png`, fullPage: true });
    });
test("readonly does not exchange callback", async ({ page }) => {
    await page.goto(path + "&readonly");
    await expect(page.getByRole("button", { name: "Verify GitHub account" })).toBeDisabled();
    expect(await page.evaluate(() => (window as unknown as { githubCalls: unknown[] }).githubCalls.length)).toBe(0);
});

test("manifest return and creation form", async ({ page }) => {
    await page.goto(path + "&manifest");
    await expect(page.getByRole("button", { name: "Install GitHub App" })).toBeVisible();
    await expect
        .poll(() =>
            page.evaluate(
                () =>
                    (window as unknown as { githubCalls: { url: string }[] }).githubCalls.filter((call) => call.url.endsWith("manifest/complete"))
                        .length
            )
        )
        .toBe(1);
    await page.goto("/src/pages/BoardPage/components/settings/GitHubOnboarding.fixture.html?new");
    let submitted = "";
    await page.route("https://github.com/settings/apps/new?*", async (route) => {
        submitted = route.request().postData() ?? "";
        await route.fulfill({ contentType: "text/html", body: "<p>GitHub registration</p>" });
    });
    await page.getByRole("button", { name: "Create GitHub App" }).click();
    await expect.poll(() => submitted).toContain("manifest=");
    expect(JSON.parse(new URLSearchParams(submitted).get("manifest")!)).toMatchObject({ name: "Langboard" });
});
