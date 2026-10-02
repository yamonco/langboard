import { test, expect } from "@playwright/test";
import type { IWorkflowStage } from "@/controllers/api/settings/workflowStages/useWorkflowStages";

const existing = (): IWorkflowStage => ({
    uid: "existing",
    key: "closed",
    name: "Closed",
    description: "Accepted work",
    color: "#64748B",
    order: 0,
    is_builtin: true,
    is_active: true,
    counts_as_completed: true,
    active_queue_policy: "exclude",
    overdue_policy: "suppress",
    entry_effects: [],
    translations: {
        en: { name: "Closed", description: "Accepted work" },
        ko: { name: "완료", description: "완료 업무" },
        ja: { name: "完了", description: "完了業務" },
        zh: { name: "已完成", description: "已完成工作" },
    },
});
for (const width of [1280, 390])
    test(`registry edit roundtrip and failure preserve draft at ${width}px`, async ({ page }) => {
        await page.setViewportSize({ width, height: 844 });
        let stages: IWorkflowStage[] = [existing()];
        let fail = true;
        let saves = 0;
        await page.route("**/settings/workflow-stages**", async (route) => {
            const headers = {
                "Access-Control-Allow-Origin": "http://127.0.0.1:4194",
                "Access-Control-Allow-Credentials": "true",
                "Access-Control-Allow-Methods": "GET,POST,PUT,OPTIONS",
                "Access-Control-Allow-Headers": "content-type,authorization,content-encoding",
            };
            if (route.request().method() === "OPTIONS") return route.fulfill({ status: 204, headers });
            if (route.request().method() === "GET") return route.fulfill({ headers, json: { stages } });
            if (route.request().url().endsWith("/deactivate")) {
                stages = stages.map((stage) => ({ ...stage, is_active: false }));
                return route.fulfill({ headers, json: { stage: stages[0] } });
            }
            saves++;
            if (fail) {
                fail = false;
                return route.fulfill({ status: 500, headers, json: { error: "test unavailable" } });
            }
            const stage = { ...route.request().postDataJSON(), uid: "saved", is_active: true, is_builtin: false };
            stages = [stage];
            return route.fulfill({ headers, json: { stage } });
        });
        await page.goto("/src/pages/SettingsPage/WorkflowStages.fixture.html");
        await page.getByRole("button", { name: /^Closed/ }).click();
        await expect(page.getByLabel("Machine key", { exact: true })).toBeDisabled();
        await page.getByRole("button", { name: "Close", exact: true }).click();
        await page.getByRole("button", { name: "New stage", exact: true }).click();
        await page.getByLabel("Machine key", { exact: true }).fill("released");
        await page.getByLabel("Stage name", { exact: true }).fill("Released");
        await page.getByLabel("Stage description", { exact: true }).fill("Accepted delivery");
        await page.getByRole("button", { name: "Color", exact: true }).click();
        const picker = page.locator("[data-radix-popper-content-wrapper]").last();
        await expect(picker.locator(".react-colorful")).toBeVisible();
        await picker.locator("input").fill("#FF9500");
        await expect(picker.locator("input")).toHaveValue("#FF9500");
        await picker.getByRole("button", { name: "Save", exact: true }).click();
        await expect(page.getByLabel("Color hex code", { exact: true })).toHaveValue("#FF9500");
        expect(saves).toBe(0);
        await page.getByLabel("Color hex code", { exact: true }).fill("#8B5CF6");
        await page.getByLabel("Count as completed", { exact: true }).check();
        await page.getByLabel("Active queue", { exact: true }).selectOption("exclude");
        await page.getByLabel("Hide overdue", { exact: true }).check();
        await page.getByLabel("Stop running timers", { exact: true }).check();
        await page.getByRole("button", { name: "한국어", exact: true }).click();
        await page.getByLabel("Stage name", { exact: true }).fill("출시");
        await page.getByLabel("Stage description", { exact: true }).fill("인수 완료");
        await page.getByLabel("Language code", { exact: true }).fill("fr");
        await page.getByRole("button", { name: "Add language", exact: true }).click();
        await page.getByLabel("Stage name", { exact: true }).fill("Livré");
        await page.getByRole("button", { name: "Save", exact: true }).click();
        await expect(page.getByRole("button", { name: "Save", exact: true })).toBeEnabled();
        await expect(page.getByLabel("Stage name", { exact: true })).toHaveValue("Livré");
        expect(saves).toBe(1);
        await page.getByRole("button", { name: "Save", exact: true }).click();
        await expect(page.getByRole("button", { name: "Save", exact: true })).toBeDisabled();
        expect(saves).toBe(2);
        await expect(page.getByLabel("Machine key", { exact: true })).toBeDisabled();
        await page.getByRole("button", { name: "Close", exact: true }).click();
        await page.reload();
        await page.getByRole("button", { name: /^Released/ }).click();
        await expect(page.getByLabel("Stop running timers", { exact: true })).toBeChecked();
        await expect(page.getByLabel("Color hex code", { exact: true })).toHaveValue("#8B5CF6");
        await expect(page.getByLabel("Active queue", { exact: true })).toHaveValue("exclude");
        await page.getByRole("button", { name: "한국어", exact: true }).click();
        await expect(page.getByLabel("Stage name", { exact: true })).toHaveValue("출시");
        await page.getByRole("button", { name: "fr", exact: true }).click();
        await expect(page.getByLabel("Stage name", { exact: true })).toHaveValue("Livré");
        expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBe(width);
        await page.getByRole("button", { name: "Deactivate", exact: true }).click();
        const confirm = page.getByRole("dialog", { name: "Deactivate", exact: true });
        await expect(confirm).toBeVisible();
        await confirm.getByRole("button", { name: "Cancel", exact: true }).click();
        await expect(confirm).not.toBeVisible();
        await expect(page.getByRole("button", { name: "Deactivate", exact: true })).toBeEnabled();
        await page.getByRole("button", { name: "Deactivate", exact: true }).click();
        await confirm.getByRole("button", { name: "Deactivate", exact: true }).click();
        await expect(page.getByRole("dialog")).not.toBeVisible();
        await expect(page.getByRole("button", { name: /^Released.*Inactive/ })).toBeVisible();
    });

test("read-only stage settings prevent mutations", async ({ page }) => {
    let writes = 0;
    await page.route("**/settings/workflow-stages**", (route) => {
        const headers = {
            "Access-Control-Allow-Origin": "http://127.0.0.1:4194",
            "Access-Control-Allow-Credentials": "true",
            "Access-Control-Allow-Headers": "content-type,authorization",
        };
        if (route.request().method() === "OPTIONS") return route.fulfill({ status: 204, headers });
        if (route.request().method() !== "GET") writes++;
        return route.fulfill({ headers, json: { stages: [existing()] } });
    });
    await page.goto("/src/pages/SettingsPage/WorkflowStages.fixture.html?readonly=1");
    await expect(page.getByRole("button", { name: "New stage", exact: true })).not.toBeVisible();
    await page.getByRole("button", { name: /^Closed/ }).click();
    await expect(page.getByLabel("Stage name", { exact: true })).toBeDisabled();
    await expect(page.getByRole("button", { name: "Save", exact: true })).toBeDisabled();
    await expect(page.getByRole("button", { name: "Deactivate", exact: true })).not.toBeVisible();
    expect(writes).toBe(0);
});

test("discard confirmation preserves draft on cancel and closes without writes on confirm", async ({ page }) => {
    let writes = 0;
    page.on("dialog", () => {
        throw new Error("Native confirmation must not open");
    });
    await page.route("**/settings/workflow-stages**", (route) => {
        const headers = {
            "Access-Control-Allow-Origin": "http://127.0.0.1:4194",
            "Access-Control-Allow-Credentials": "true",
            "Access-Control-Allow-Headers": "content-type,authorization",
        };
        if (route.request().method() === "OPTIONS") return route.fulfill({ status: 204, headers });
        if (route.request().method() !== "GET") writes++;
        return route.fulfill({ headers, json: { stages: [existing()] } });
    });
    await page.goto("/src/pages/SettingsPage/WorkflowStages.fixture.html");
    await page.getByRole("button", { name: /^Closed/ }).click();
    await page.getByLabel("Stage name", { exact: true }).fill("Unsaved name");
    await page.getByRole("button", { name: "Close", exact: true }).click();
    const confirmation = page.getByRole("dialog", { name: "Discard unsaved changes?", exact: true });
    await expect(confirmation).toBeVisible();
    await confirmation.getByRole("button", { name: "Cancel", exact: true }).click();
    await expect(page.getByLabel("Stage name", { exact: true })).toHaveValue("Unsaved name");
    await page.getByRole("button", { name: "Close", exact: true }).click();
    await confirmation.getByRole("button", { name: "Discard changes", exact: true }).click();
    await expect(page.getByRole("dialog")).not.toBeVisible();
    expect(writes).toBe(0);
});
