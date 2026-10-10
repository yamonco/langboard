import { test, expect } from "@playwright/test";
const path = "/src/pages/BoardPage/components/settings/AppWorkflow.fixture.html";
for (const panel of [false, true]) {
    test(`independent app workflow is configurable ${panel ? "with" : "without"} a panel`, async ({ page }) => {
        await page.goto(`${path}?store&external${panel ? "&panel" : ""}`);
        const app = page.getByRole("article").filter({ has: page.getByRole("heading", { name: "Example ERP", exact: true }) });
        await app.getByRole("button", { name: "Configure workflow", exact: true }).click();
        await expect(page.getByRole("heading", { name: "Example ERP", exact: true })).toBeVisible();
        await page.getByRole("combobox").selectOption("two");
        await page.getByRole("button", { name: "Save workflow mapping" }).click();
        await expect.poll(() => page.evaluate(() => (window as unknown as { workflowWrites: unknown[] }).workflowWrites.length)).toBe(1);
        expect(await page.evaluate(() => (window as unknown as { workflowWrites: unknown[] }).workflowWrites)).toEqual([
            {
                url: "/board/fixture/settings/apps/example-erp/workflow",
                binding_uid: "binding",
                workflow_mapping: { active: "two" },
                expected_revision: "a".repeat(64),
                enable_transitions: false,
            },
        ]);
    });
}
for (const width of [1440, 390]) {
    test(`edit and discard at ${width}px`, async ({ page }) => {
        page.on("console", (msg) => {
            if (msg.type() === "error") console.log("CONSOLE", msg.text());
        });
        page.on("requestfailed", (req) => console.log("FAIL", req.url(), req.failure()));
        page.on("pageerror", (error) => console.log("PAGEERROR", error.message));
        await page.setViewportSize({ width, height: 850 });
        await page.goto(path);

        const selects = page.getByRole("combobox");
        await expect(selects.first()).toHaveValue("one");
        await expect(selects.first().getByRole("option", { name: "Implementation" })).toHaveCount(1);
        await selects.first().selectOption("two");
        await expect(page.getByRole("button", { name: "Retry" })).toBeDisabled();
        await page.getByRole("button", { name: "Discard changes" }).click();
        await expect(selects.first()).toHaveValue("one");
        await selects.first().selectOption("two");
        await page.getByRole("button", { name: "Save workflow mapping" }).click();
        await expect.poll(() => page.evaluate(() => (window as unknown as { workflowWrites: unknown[] }).workflowWrites.length)).toBe(1);
        const writes = await page.evaluate(() => (window as unknown as { workflowWrites: unknown[] }).workflowWrites);
        expect(writes[0]).toMatchObject({ workflow_mapping: { active: "two" }, enable_transitions: false, expected_revision: "a".repeat(64) });
        expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
    });
}

for (const width of [1440, 390]) {
    for (const create of [false, true]) {
        test(`repair missing stage ${create ? "create" : "assign"} at ${width}px`, async ({ page }) => {
            await page.setViewportSize({ width, height: 850 });
            await page.goto(`${path}?missing`);
            if (create) {
                await page.getByRole("textbox", { name: "New workflow column name" }).fill("In progress");
                await page.getByRole("button", { name: "Create column with stage" }).click();
            } else {
                await page.getByRole("combobox", { name: "Existing column for stage" }).selectOption("two");
                await page.getByRole("button", { name: "Assign stage to column" }).click();
            }
            await expect(page.getByRole("textbox", { name: "New workflow column name" })).toHaveCount(0);
            const writes = await page.evaluate(() => (window as unknown as { workflowWrites: unknown[] }).workflowWrites);
            expect(writes).toEqual([
                create
                    ? { name: "In progress", workflow_stage: "active", url: "/board/fixture/column" }
                    : { workflow_stage: "active", expected_workflow_stage: null, url: "/board/fixture/column/two/workflow-stage" },
            ]);
            expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
        });
    }
}
test("read-only users cannot repair missing stages", async ({ page }) => {
    await page.goto(`${path}?missing&readonly`);
    await expect(page.getByRole("combobox", { name: "Existing column for stage" })).toBeDisabled();
    await expect(page.getByRole("button", { name: "Assign stage to column" })).toBeDisabled();
    await expect(page.getByRole("button", { name: "Create column with stage" })).toBeDisabled();
});

test("replacing a board-wide stage requires confirmation", async ({ page }) => {
    await page.goto(`${path}?missing&replace`);
    await page.getByRole("combobox", { name: "Existing column for stage" }).selectOption("two");
    await page.getByRole("button", { name: "Assign stage to column" }).click();
    await expect(page.getByText("Replacing this stage changes")).toBeVisible();
    expect(await page.evaluate(() => (window as unknown as { workflowWrites: unknown[] }).workflowWrites.length)).toBe(0);
    await page.getByRole("button", { name: "Cancel", exact: true }).click();
    await expect(page.getByRole("button", { name: "Confirm stage replacement" })).toHaveCount(0);
    await page.getByRole("button", { name: "Assign stage to column" }).click();
    await page.getByRole("button", { name: "Confirm stage replacement" }).click();
    await expect.poll(() => page.evaluate(() => (window as unknown as { workflowWrites: unknown[] }).workflowWrites.length)).toBe(1);
});

for (const width of [1440, 390]) {
    test(`App Store entry and draft preservation at ${width}px`, async ({ page }) => {
        await page.setViewportSize({ width, height: 850 });
        await page.goto(`${path}?store`);
        await expect(page.getByRole("heading", { name: "App Store" })).toBeVisible();
        await expect(page.getByRole("heading", { name: "Dokploy" })).toBeVisible();
        await page.getByText("Selected resources: 2", { exact: true }).click();
        await expect(page.getByText("Denied · 1", { exact: true })).toBeVisible();
        await expect(page.getByText("Degraded · 1", { exact: true })).toBeVisible();
        await expect(page.getByRole("button", { name: "Workflow contract pending" })).toBeDisabled();
        await page
            .getByRole("article")
            .filter({ has: page.getByRole("heading", { name: "GitHub" }) })
            .getByRole("button")
            .click();
        const mapping = page.getByRole("combobox");
        await expect(mapping).toHaveValue("one");
        await mapping.selectOption("two");
        await expect(page.getByRole("button", { name: "Back to App Store" })).toBeDisabled();
        await page.getByRole("button", { name: "Discard changes" }).click();
        await page.getByRole("button", { name: "Back to App Store" }).click();
        await expect(page.getByRole("heading", { name: "App Store" })).toBeVisible();
        expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
    });
}

test("board App disable confirms and refreshes the stored state", async ({ page }) => {
    await page.goto(`${path}?store&enabled`);
    await page.getByRole("button", { name: "Disable App", exact: true }).click();
    expect(await page.evaluate(() => (window as unknown as { workflowWrites: unknown[] }).workflowWrites.length)).toBe(0);
    await page.getByRole("button", { name: "Confirm disable App" }).click();
    await expect(page.getByRole("button", { name: "Disable App", exact: true })).toHaveCount(0);
    const writes = await page.evaluate(() => (window as unknown as { workflowWrites: unknown[] }).workflowWrites);
    expect(writes).toEqual([{ binding_uid: "binding", expected_revision: "a".repeat(64), url: "/board/fixture/settings/apps/github/disable" }]);
});

for (const locale of ["en-US", "ko-KR", "ja-JP", "zh-CN"]) {
    test(`App resource counts use account locale ${locale}`, async ({ page }) => {
        await page.goto(`${path}?store&large&lang=${locale}`);
        const app = page.locator("article").filter({ has: page.getByRole("heading", { name: "GitHub", exact: true }) });
        await expect(app.locator("summary")).toContainText("2,468");
        await app.locator("summary").click();
        await expect(app).toContainText("1,234");
    });
}

for (const width of [1440, 390]) {
    test(`inbound connections register and disconnect at ${width}px`, async ({ page }) => {
        await page.setViewportSize({ width, height: 850 });
        await page.goto(`${path}?store&external`);
        expect(await page.evaluate(() => (window as unknown as { inboundReads: string[] }).inboundReads.length)).toBe(0);
        await page.getByRole("button", { name: "Manage service connections" }).click();
        await expect(page.getByText("connection1 · Connected", { exact: true })).toBeVisible();
        await page.getByRole("button", { name: "Register service connection", exact: true }).click();
        expect(await page.evaluate(() => (window as unknown as { workflowWrites: unknown[] }).workflowWrites.length)).toBe(0);
        await page.getByRole("button", { name: "Confirm", exact: true }).click();
        await expect(page.getByText("connection2 · Connected", { exact: true })).toBeVisible();
        const first = page.getByRole("listitem").filter({ hasText: "connection1" });
        await first.getByRole("button", { name: "Disconnect", exact: true }).click();
        await page.getByRole("button", { name: "Confirm", exact: true }).click();
        await expect(first.getByRole("button", { name: "Disconnect", exact: true })).toBeDisabled();
        expect(await page.evaluate(() => (window as unknown as { workflowWrites: unknown[] }).workflowWrites)).toEqual([
            { url: "/settings/apps/registry/example-erp/inbound-connections", app_revision: "a".repeat(64), organization_uid: null },
            { url: "/settings/apps/inbound-connections/connection1/disconnect", expected_revision: "a".repeat(64) },
        ]);
        expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
    });
}

test("inbound failure blocks another mutation until explicit refresh", async ({ page }) => {
    await page.goto(`${path}?store&external&connectionfail`);
    await page.getByRole("button", { name: "Manage service connections" }).click();
    await page.getByRole("button", { name: "Disconnect", exact: true }).click();
    await page.getByRole("button", { name: "Confirm", exact: true }).click();
    await expect(page.getByRole("alert")).toContainText("Refresh the list");
    await expect(page.getByRole("button", { name: "Confirm", exact: true })).toBeDisabled();
    await page.getByRole("button", { name: "Retry", exact: true }).click();
    await expect(page.getByRole("alert")).toHaveCount(0);
    expect(await page.evaluate(() => (window as unknown as { workflowWrites: unknown[] }).workflowWrites.length)).toBe(1);
});

test("independent board consent requires explicit selection and save", async ({ page }) => {
    await page.goto(`${path}?store&external&consent`);
    const app = page.getByRole("article").filter({ has: page.getByRole("heading", { name: "Example ERP", exact: true }) });
    await app.getByRole("button", { name: "Review permissions", exact: true }).click();
    await app.getByRole("checkbox", { name: "panels.render", exact: true }).click();
    expect(await page.evaluate(() => (window as unknown as { workflowWrites: unknown[] }).workflowWrites.length)).toBe(0);
    await app.getByRole("button", { name: "Save reviewed permissions", exact: true }).click();
    await expect.poll(() => page.evaluate(() => (window as unknown as { workflowWrites: unknown[] }).workflowWrites.length)).toBe(1);
    expect(await page.evaluate(() => (window as unknown as { workflowWrites: unknown[] }).workflowWrites[0])).toEqual({
        url: "/board/fixture/settings/apps/example-erp/consent", app_revision: "a".repeat(64),
        binding_uid: "binding", expected_revision: "a".repeat(64), capabilities: ["panels.render"],
    });
});

test("disabled app consent can be revoked while new grants remain blocked", async ({ page }) => {
    await page.goto(`${path}?store&external&consent&consentdisabled`);
    const app = page.getByRole("article").filter({ has: page.getByRole("heading", { name: "Example ERP", exact: true }) });
    await app.getByRole("button", { name: "Review permissions", exact: true }).click();
    await expect(app.getByRole("button", { name: "Save reviewed permissions", exact: true })).toBeDisabled();
    await app.getByRole("button", { name: "Clear selection", exact: true }).click();
    await app.getByRole("button", { name: "Save reviewed permissions", exact: true }).click();
    await expect.poll(() => page.evaluate(() => (window as unknown as { workflowWrites: unknown[] }).workflowWrites.length)).toBe(1);
    expect(await page.evaluate(() => (window as unknown as { workflowWrites: { capabilities: string[] }[] }).workflowWrites[0].capabilities)).toEqual([]);
});

test("consent failure requires explicit catalog refresh before another save", async ({ page }) => {
    await page.goto(`${path}?store&external&consent&consentfail`);
    const app = page.getByRole("article").filter({ has: page.getByRole("heading", { name: "Example ERP", exact: true }) });
    await app.getByRole("button", { name: "Review permissions", exact: true }).click();
    await app.getByRole("checkbox", { name: "panels.render", exact: true }).click();
    await app.getByRole("button", { name: "Save reviewed permissions", exact: true }).click();
    await expect(app.getByRole("alert")).toBeVisible();
    await expect(app.getByRole("button", { name: "Save reviewed permissions", exact: true })).toBeDisabled();
    await app.getByRole("button", { name: "Back and refresh", exact: true }).click();
    await app.getByRole("button", { name: "Review permissions", exact: true }).click();
    await expect(app.getByRole("alert")).toHaveCount(0);
    await expect(app.getByRole("checkbox", { name: "panels.render", exact: true })).not.toBeChecked();
    expect(await page.evaluate(() => (window as unknown as { workflowWrites: unknown[] }).workflowWrites.length)).toBe(1);
});

test("read-only board member can review but cannot consent", async ({ page }) => {
    await page.goto(`${path}?store&external&consent&readonly`);
    const app = page.getByRole("article").filter({ has: page.getByRole("heading", { name: "Example ERP", exact: true }) });
    await app.getByRole("button", { name: "Review permissions", exact: true }).click();
    await expect(app.getByRole("checkbox", { name: "panels.render", exact: true })).toBeDisabled();
    await expect(app.getByRole("button", { name: "Save reviewed permissions", exact: true })).toBeDisabled();
    await expect(app.getByRole("button", { name: "Clear selection", exact: true })).toBeDisabled();
    expect(await page.evaluate(() => (window as unknown as { workflowWrites: unknown[] }).workflowWrites.length)).toBe(0);
});


for (const width of [1440, 390]) {
    test(`service resource selection and removal at ${width}px`, async ({ page }) => {
        await page.setViewportSize({ width, height: 850 });
        await page.goto(`${path}?store&external&consent`);
        await page.getByRole("button", { name: "Manage service connections" }).click();
        await page.getByRole("button", { name: "Manage service resources" }).click();
        await page.getByRole("combobox", { name: "Resource type", exact: true }).selectOption("project");
        await page.getByRole("textbox", { name: "External resource ID", exact: true }).fill("erp-project");
        await page.getByRole("button", { name: "Select resource", exact: true }).click();
        expect(await page.evaluate(() => (window as unknown as { workflowWrites: unknown[] }).workflowWrites.length)).toBe(0);
        await page.getByRole("button", { name: "Confirm", exact: true }).click();
        await expect(page.getByRole("button", { name: "Remove selection", exact: true })).toBeVisible();
        await page.getByRole("button", { name: "Remove selection", exact: true }).click();
        await page.getByRole("button", { name: "Confirm", exact: true }).click();
        expect(await page.evaluate(() => (window as unknown as { workflowWrites: unknown[] }).workflowWrites)).toEqual([
            { url: "/board/fixture/settings/apps/example-erp/inbound-connections/connection1/resources", app_revision: "a".repeat(64),
                binding_uid: "binding", expected_revision: "b".repeat(64), resource_type: "project", external_resource_id: "erp-project",
                selected: true, expected_access_revision: null },
            { url: "/board/fixture/settings/apps/example-erp/inbound-connections/connection1/resources", app_revision: "a".repeat(64),
                binding_uid: "binding", expected_revision: "b".repeat(64), resource_type: "project", external_resource_id: "erp-project",
                selected: false, expected_access_revision: 1 },
        ]);
        expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
    });
}

test("service resource failure requires refresh", async ({ page }) => {
    await page.goto(`${path}?store&external&consent&resourcefail`);
    await page.getByRole("button", { name: "Manage service connections" }).click();
    await page.getByRole("button", { name: "Manage service resources" }).click();
    await page.getByRole("combobox", { name: "Resource type", exact: true }).selectOption("project");
    await page.getByRole("textbox", { name: "External resource ID", exact: true }).fill("erp-project");
    await page.getByRole("button", { name: "Select resource", exact: true }).click();
    await page.getByRole("button", { name: "Confirm", exact: true }).click();
    await expect(page.getByRole("alert")).toBeVisible();
    await expect(page.getByRole("button", { name: "Confirm", exact: true })).toBeDisabled();
    await page.getByRole("button", { name: "Retry", exact: true }).click();
    await expect(page.getByRole("alert")).toHaveCount(0);
    expect(await page.evaluate(() => (window as unknown as { workflowWrites: unknown[] }).workflowWrites.length)).toBe(1);
});


for (const width of [1440, 390]) {
    test(`service credential is displayed once and revoked at ${width}px`, async ({ page }) => {
        await page.setViewportSize({ width, height: 850 });
        await page.goto(`${path}?store&external`);
        await page.getByRole("button", { name: "Manage service connections" }).click();
        await page.getByRole("button", { name: "Manage credentials" }).click();
        await page.getByRole("button", { name: "Issue credential", exact: true }).click();
        expect(await page.evaluate(() => (window as unknown as { workflowWrites: unknown[] }).workflowWrites.length)).toBe(0);
        await page.getByRole("button", { name: "Confirm", exact: true }).click();
        await expect(page.getByRole("textbox", { name: "Service credential", exact: true })).toHaveValue("synthetic-once-value");
        await page.getByRole("button", { name: "Hide value", exact: true }).click();
        await expect(page.getByRole("textbox", { name: "Service credential", exact: true })).toHaveCount(0);
        await page.getByRole("button", { name: "Revoke credential", exact: true }).click();
        await page.getByRole("button", { name: "Confirm", exact: true }).click();
        await expect(page.getByRole("button", { name: "Revoke credential", exact: true })).toBeDisabled();
        expect(await page.evaluate(() => (window as unknown as { workflowWrites: unknown[] }).workflowWrites)).toEqual([
            { url: "/settings/apps/connections/connection1/credentials", expires_in_seconds: 3600 },
            { url: "/settings/apps/connections/connection1/credentials/credential1/revoke" },
        ]);
        expect(await page.evaluate(() => JSON.stringify(localStorage).includes("synthetic-once-value") || JSON.stringify(sessionStorage).includes("synthetic-once-value"))).toBe(false);
        expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
    });
}

test("lost credential response requires receipt recovery without automatic issuance", async ({ page }) => {
    await page.goto(`${path}?store&external&credentialfail`);
    await page.getByRole("button", { name: "Manage service connections" }).click();
    await page.getByRole("button", { name: "Manage credentials" }).click();
    await page.getByRole("button", { name: "Issue credential", exact: true }).click();
    await page.getByRole("button", { name: "Confirm", exact: true }).click();
    await expect(page.getByRole("alert")).toBeVisible();
    await expect(page.getByRole("button", { name: "Confirm", exact: true })).toBeDisabled();
    await page.getByRole("button", { name: "Retry", exact: true }).click();
    await expect(page.getByRole("button", { name: "Revoke credential", exact: true })).toBeEnabled();
    await expect(page.getByRole("textbox", { name: "Service credential", exact: true })).toHaveCount(0);
    expect(await page.evaluate(() => (window as unknown as { workflowWrites: unknown[] }).workflowWrites.length)).toBe(1);
});

test("disabled app exposes credential cleanup but prevents issuance", async ({ page }) => {
    await page.goto(`${path}?store&external&consentdisabled`);
    await page.getByRole("button", { name: "Manage service connections" }).click();
    await page.getByRole("button", { name: "Manage credentials" }).click();
    await expect(page.getByRole("button", { name: "Issue credential", exact: true })).toBeDisabled();
});
