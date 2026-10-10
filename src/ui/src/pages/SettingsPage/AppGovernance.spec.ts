import { expect, test } from "@playwright/test";

for (const width of [1280, 390]) {
    test(`policy submits once and retains failed draft at ${width}px`, async ({ page }) => {
        await page.setViewportSize({ width, height: 850 });
        const writes: unknown[] = [];
        let fail = true;
        await page.route("**/settings/apps/governance/organizations", (route) =>
            route.fulfill({
                headers: { "Access-Control-Allow-Origin": "http://127.0.0.1:4216", "Access-Control-Allow-Credentials": "true" },
                json: { items: [], next_cursor: null },
            })
        );
        await page.route("**/settings/apps/governance", async (route) => {
            const headers = {
                "Access-Control-Allow-Origin": "http://127.0.0.1:4216",
                "Access-Control-Allow-Credentials": "true",
                "Access-Control-Allow-Methods": "GET,PUT,OPTIONS",
                "Access-Control-Allow-Headers": "content-type,authorization,content-encoding",
            };
            if (route.request().method() === "OPTIONS") return route.fulfill({ status: 204, headers });
            if (route.request().method() === "GET")
                return route.fulfill({
                    status: 200,
                    headers,
                    json: {
                        mode: "approved_only",
                        effective_mode: "approved_only",
                        revision: "a".repeat(64),
                    },
                });
            writes.push(route.request().postDataJSON());
            await route.fulfill({
                status: fail ? 500 : 200,
                headers,
                json: fail
                    ? { detail: "failed" }
                    : {
                          mode: "disabled",
                          effective_mode: "disabled",
                          revision: "b".repeat(64),
                      },
            });
        });
        await page.goto("/src/pages/SettingsPage/AppGovernance.fixture.html");
        await page.locator("input[value=disabled]").check();
        await page.locator("form").evaluate((form) => {
            form.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }));
            form.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }));
        });
        await expect(page.getByRole("alert")).toBeVisible();
        expect(writes).toEqual([{ mode: "disabled", expected_revision: "a".repeat(64) }]);
        await expect(page.locator("input[value=disabled]")).toBeChecked();
        fail = false;
        await page.getByRole("button", { name: "Save", exact: true }).click();
        await expect(page.getByRole("status")).toBeVisible();
        expect(writes).toHaveLength(2);
        expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    });
}

test("organization owner edits inheritance without reading global policy and keeps a conflict draft", async ({ page }) => {
    const origin = "http://127.0.0.1:4216";
    const headers = {
        "Access-Control-Allow-Origin": origin,
        "Access-Control-Allow-Credentials": "true",
        "Access-Control-Allow-Methods": "GET,PUT,OPTIONS",
        "Access-Control-Allow-Headers": "content-type,authorization,content-encoding",
    };
    const writes: unknown[] = [];
    let globalReads = 0;
    let conflict = false;
    await page.route("**/settings/apps/governance**", async (route) => {
        const path = new URL(route.request().url()).pathname;
        if (route.request().method() === "OPTIONS") return route.fulfill({ status: 204, headers });
        if (path.endsWith("/organizations"))
            return route.fulfill({ headers, json: { items: [{ uid: "org-one", name: "Organization One" }], next_cursor: null } });
        if (path.endsWith("/governance")) {
            globalReads++;
            return route.fulfill({ status: 403, headers, json: { detail: "forbidden" } });
        }
        expect(path).toContain("/organizations/org-one");
        if (route.request().method() === "GET")
            return route.fulfill({ headers, json: { mode: null, effective_mode: "approved_only", revision: "a".repeat(64) } });
        writes.push(route.request().postDataJSON());
        return route.fulfill({
            status: conflict ? 409 : 200,
            headers,
            json: conflict
                ? { detail: "conflict" }
                : { mode: route.request().postDataJSON().mode, effective_mode: "approved_only", revision: "b".repeat(64) },
        });
    });
    await page.goto("/src/pages/SettingsPage/AppGovernance.fixture.html?owner");
    await page.getByLabel("Policy scope").selectOption("org-one");
    await expect(page.locator("input[value=inherit]")).toBeChecked();
    await page.locator("input[value=disabled]").check();
    await expect(page.getByLabel("Policy scope")).toBeDisabled();
    await page.getByRole("button", { name: "Cancel", exact: true }).click();
    await expect(page.getByLabel("Policy scope")).toBeEnabled();
    await page.locator("input[value=disabled]").check();
    conflict = true;
    await page.getByRole("button", { name: "Save", exact: true }).click();
    await expect(page.getByRole("alert")).toBeVisible();
    await expect(page.locator("input[value=disabled]")).toBeChecked();
    await expect(page.getByRole("button", { name: "Save", exact: true })).toBeDisabled();
    await page.getByRole("button", { name: "Cancel", exact: true }).click();
    await page.locator("input[value=disabled]").check();
    conflict = false;
    await page.getByRole("button", { name: "Save", exact: true }).click();
    await expect(page.getByRole("status")).toBeVisible();
    await page.locator("input[value=inherit]").check();
    await page.getByRole("button", { name: "Save", exact: true }).click();
    await expect(page.getByRole("button", { name: "Save", exact: true })).toBeDisabled();
    expect(writes).toHaveLength(3);
    expect(writes.at(-1)).toEqual({ mode: null, expected_revision: "b".repeat(64) });
    expect(globalReads).toBe(0);
});
