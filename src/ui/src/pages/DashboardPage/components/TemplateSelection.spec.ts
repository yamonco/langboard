import { expect, test } from "@playwright/test";
for (const width of [1280, 390])
    for (const [locale, expected] of [
        ["en-US", "Backlog → Review"],
        ["ko-KR", "요청 → 검토"],
        ["ja-JP", "依頼 → 確認"],
        ["zh-CN", "请求 → Review"],
    ]) {
        test(`template selection consumes locale columns and retains canonical key at ${locale}/${width}`, async ({ page }) => {
            await page.setViewportSize({ width, height: 850 });
            await page.route("**/settings/project-templates", (route) =>
                route.fulfill({
                    json: {
                        templates: [
                            {
                                uid: "builtin",
                                name: "SI",
                                is_builtin: true,
                                is_default: true,
                                columns: ["Backlog", "Review"],
                                column_definitions: [
                                    {
                                        name: "Backlog",
                                        description: "Waiting",
                                        workflow_stage: "backlog",
                                        translations: {
                                            ko: { name: "요청", description: "" },
                                            ja: { name: "依頼", description: "" },
                                            zh: { name: "请求", description: "" },
                                        },
                                    },
                                    {
                                        name: "Review",
                                        description: "Acceptance",
                                        workflow_stage: "review",
                                        translations: {
                                            ko: { name: "검토", description: "" },
                                            ja: { name: "確認", description: "" },
                                            zh: { name: "", description: "" },
                                        },
                                    },
                                ],
                            },
                            { uid: "legacy", name: "Legacy", columns: ["Queue"], is_builtin: false, is_default: false },
                        ],
                    },
                })
            );
            await page.goto(`/src/pages/DashboardPage/components/TemplateSelection.fixture.html?lang=${locale}`);
            const selected = page.getByRole("combobox").last();
            await selected.click();
            await expect(page.getByRole("option", { name: `SI · ${expected}`, exact: true })).toBeVisible();
            await page.getByRole("option", { name: `SI · ${expected}`, exact: true }).click();
            await expect(page.locator("input[name=template_name]")).toHaveValue("SI");
            await selected.click();
            await page.getByRole("option", { name: "Legacy · Queue", exact: true }).click();
            await expect(page.locator("input[name=template_name]")).toHaveValue("Legacy");
            expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
        });
    }
