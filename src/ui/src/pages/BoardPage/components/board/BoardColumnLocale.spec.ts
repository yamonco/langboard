import { test, expect } from "@playwright/test";
for (const width of [1280, 390]) {
    test(`column locale presentation preserves canonical fields at ${width}px`, async ({ page }) => {
        await page.setViewportSize({ width, height: 850 });
        await page.route("**/board/board/workflow-stages", (route) => route.fulfill({ json: { stages: [] } }));
        for (const [lang, name, description, button] of [
            ["en-US", "Queue", "Waiting for work", "Column description"],
            ["ko-KR", "대기", "작업 대기", "열 설명"],
            ["ja-JP", "待機", "作業待ち", "列の説明"],
            ["zh-CN", "队列", "等待工作", "列描述"],
        ]) {
            await page.goto(`/src/pages/BoardPage/components/board/BoardColumnLocale.fixture.html?lang=${lang}`);
            await expect(page.getByText(name, { exact: true })).toBeVisible();
            await expect(page.getByTestId("canonical-editor").getByRole("textbox")).toHaveValue("Queue");
            await page.getByRole("button", { name: button, exact: true }).click();
            await expect(page.getByText(description, { exact: true })).toBeVisible();
            await expect(page.locator("output")).toHaveText(JSON.stringify({ name: "Queue", description: "Waiting for work", workflow_stage: null }));
            expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
        }
    });
}
