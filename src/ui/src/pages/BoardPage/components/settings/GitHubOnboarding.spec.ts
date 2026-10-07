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

test("fresh tab can reselect owned connection and reset", async ({ page }) => {
    await page.goto("/src/pages/BoardPage/components/settings/GitHubOnboarding.fixture.html?existing");
    await page.getByRole("combobox", { name: "Existing GitHub connection" }).selectOption("stored");
    await expect(page.getByRole("button", { name: "Verify GitHub account" })).toBeEnabled();
    await expect(page.getByRole("button", { name: "Install GitHub App" })).toBeEnabled();
    expect(await page.evaluate(() => JSON.parse(sessionStorage.getItem("github-onboarding:me:fixture")!).connection_uid)).toBe("stored");
    await page.getByRole("combobox", { name: "Existing GitHub connection" }).selectOption("");
    await expect(page.getByRole("button", { name: "Create GitHub App" })).toBeEnabled();
});

test("reused connection refreshes app metadata before install", async ({ page }) => {
    await page.goto("/src/pages/BoardPage/components/settings/GitHubOnboarding.fixture.html?existing");
    await page.getByRole("combobox", { name: "Existing GitHub connection" }).selectOption("stored");
    await page.route("https://github.com/apps/current-app/installations/new", (route) =>
        route.fulfill({ contentType: "text/html", body: "<p>Install current App</p>" })
    );
    await page.getByRole("button", { name: "Install GitHub App" }).click();
    await expect(page).toHaveURL("https://github.com/apps/current-app/installations/new");
});

test("explicit health refresh uses current resource revision", async ({ page }) => {
    await page.goto(path);
    await page.getByRole("button", { name: "Refresh repository health" }).click();
    await expect(page.getByRole("status")).toContainText("Stored resource health refreshed");
    const calls = await page.evaluate(() => (window as unknown as { githubCalls: { url: string; data: unknown }[] }).githubCalls);
    expect(calls.find((call) => call.url.endsWith("/resources/refresh"))?.data).toMatchObject({
        connection_uid: "conn",
        expected_revision: "a".repeat(64),
    });
});

test("health refresh continues only on explicit request", async ({ page }) => {
    await page.goto(path + "&healthpages");
    await page.getByRole("button", { name: "Refresh repository health" }).click();
    await page.getByRole("button", { name: "Refresh next repositories" }).click();
    await expect(page.getByRole("button", { name: "Refresh repository health" })).toBeVisible();
    const calls = await page.evaluate(() =>
        (window as unknown as { githubCalls: { url: string; data: unknown }[] }).githubCalls.filter((call) => call.url.endsWith("/resources/refresh"))
    );
    expect(calls).toHaveLength(2);
    expect(calls[1].data).toMatchObject({ after: "cursor" });
});

test("next installation page requests a new page-bound authorization", async ({ page }) => {
    await page.goto(path + "&installpages");
    // Native API adapter calls are inspected before navigation via a route hold.
    await page.route("https://github.com/login/oauth/authorize?*", async (route) => {
        await route.fulfill({ contentType: "text/html", body: "<p>Authorize next page</p>" });
    });
    const callPromise = page.waitForEvent("console", (message) => message.text().startsWith("authorization-page:"));
    await page.getByRole("button", { name: "More installations" }).click();
    const message = await callPromise;
    expect(message.text()).toBe("authorization-page:2");
    await expect(page).toHaveURL(/github.com\/login\/oauth\/authorize/);
});

for (const width of [1440, 390])
    test(`stored connection health is explicit and paged ${width}`, async ({ page }) => {
        await page.setViewportSize({ width, height: 900 });
        await page.goto("/src/pages/BoardPage/components/settings/GitHubOnboarding.fixture.html?existing");
        await page.getByRole("combobox", { name: "Existing GitHub connection" }).selectOption("stored");
        await page.getByRole("button", { name: "Show GitHub connection health" }).click();
        const health = page.getByLabel("GitHub connection health", { exact: true });
        await expect(health).toContainText("Stored evidence only");
        await expect(health).toContainText("Selected: 4");
        await expect(health).toContainText("Unavailable: 1");
        const jobs = page.getByLabel("Background verification", { exact: true });
        await expect(jobs).toContainText("Needs attention");
        await expect(jobs).toContainText("shared across boards");
        await jobs.getByRole("button", { name: "Reload job status" }).click();
        const jobCalls = await page.evaluate(() =>
            (window as unknown as { githubCalls: { url: string }[] }).githubCalls.filter((call) => call.url.endsWith("/jobs"))
        );
        expect(jobCalls).toHaveLength(2);
        await page.getByRole("button", { name: "More installation health" }).click();
        await expect(health.getByRole("listitem")).toHaveCount(2);
        await expect(page.getByRole("button", { name: "More installation health" })).toHaveCount(0);
        expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
        await page.screenshot({ path: `test-results/github-health-${width}.png`, fullPage: true });
        await page.getByRole("combobox", { name: "Existing GitHub connection" }).selectOption("");
        await expect(health).toHaveCount(0);
    });
