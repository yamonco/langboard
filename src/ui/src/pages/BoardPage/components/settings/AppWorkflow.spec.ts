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
