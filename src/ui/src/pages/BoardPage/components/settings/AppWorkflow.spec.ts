import { test, expect } from "@playwright/test";
const path = "/src/pages/BoardPage/components/settings/AppWorkflow.fixture.html";
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
        await expect(selects.nth(1)).toHaveValue("one");
        await expect(selects.nth(1).getByRole("option", { name: "Implementation" })).toHaveCount(1);
        await selects.nth(1).selectOption("two");
        await expect(selects.first()).toBeDisabled();
        await expect(page.getByRole("button", { name: "Retry" })).toBeDisabled();
        await page.getByRole("button", { name: "Discard changes" }).click();
        await expect(selects.nth(1)).toHaveValue("one");
        await selects.nth(1).selectOption("two");
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
