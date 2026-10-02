import { test, expect } from "@playwright/test";
for (const width of [1280, 390])
    test(`template column editor retains failed draft and sends structured columns at ${width}px`, async ({ page }) => {
        await page.setViewportSize({ width, height: 850 });
        await page.route("**/settings/global-labels", (route) =>
            route.fulfill({ json: { labels: [{ uid: "global", name: "Question", description: "Ask", color: "#8B5CF6", translations: {} }] } })
        );
        let fail = true;
        let writes = 0;
        await page.route("**/settings/workflow-stages", (route) => route.fulfill({ json: { stages: [] } }));
        await page.route("**/settings/project-templates**", async (route) => {
            if (route.request().method() === "GET")
                return route.fulfill({
                    json: {
                        templates: [
                            { uid: "one", name: "Custom", columns: ["Queue"], column_descriptions: ["Legacy"], is_builtin: false, is_default: true },
                        ],
                    },
                });
            writes++;
            const body = route.request().postDataJSON();
            expect(body.description).toBe("Reusable support board");
            expect(body.global_label_uids).toEqual(["global"]);
            expect(body.columns[0]).toMatchObject({
                name: "Queue",
                description: "Edited guidance",
                workflow_stage: null,
                translations: { ko: { name: "대기", description: "" } },
            });
            if (fail) {
                fail = false;
                return route.fulfill({ status: 500, json: {} });
            }
            await route.fulfill({
                json: {
                    template: {
                        ...body,
                        uid: "one",
                        columns: body.columns.map((x: { name: string }) => x.name),
                        column_definitions: body.columns,
                        is_default: true,
                    },
                },
            });
        });
        await page.goto("/src/pages/SettingsPage/ProjectTemplates.fixture.html");
        await page.getByRole("button", { name: "Edit", exact: true }).click();
        await expect(page.getByLabel("Column name", { exact: true })).toHaveValue("Queue");
        await page.getByLabel("Column description", { exact: true }).fill("Edited guidance");
        await page.getByLabel("Template description", { exact: true }).fill("Reusable support board");
        await page.getByRole("checkbox", { name: "Question" }).check();
        await page.getByRole("button", { name: "ko", exact: true }).click();
        await page.getByLabel("Column name", { exact: true }).fill("대기");
        await page.getByRole("button", { name: "Save", exact: true }).click();
        await expect(page.getByRole("alert")).toBeVisible();
        await expect(page.getByLabel("Column name", { exact: true })).toHaveValue("대기");
        await page.getByRole("button", { name: "Save", exact: true }).click();
        await expect(page.locator("form")).toHaveCount(0);
        expect(writes).toBe(2);
        expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    });
