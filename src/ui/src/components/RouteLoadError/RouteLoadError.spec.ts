import { expect, test } from "@playwright/test";

for (const [lang, refresh, dashboard] of [
    ["en-US", "Refresh", "Go to Dashboard"],
    ["ko-KR", "새로고침", "대시보드로 이동"],
    ["ja-JP", "再読み込み", "ダッシュボードへ"],
    ["zh-CN", "刷新", "前往仪表板"],
]) {
    test(`lazy route rejection recovers with manual refresh: ${lang}`, async ({ page }) => {
        await page.goto(`/src/components/RouteLoadError/RouteLoadError.fixture.html?lang=${lang}`);
        await expect(page.getByRole("alert")).toBeVisible();
        await expect(page.getByRole("link", { name: dashboard })).toHaveAttribute("href", "/dashboard");
        await expect(page.getByText("private-chunk-path", { exact: false })).toHaveCount(0);
        await expect(page.getByText("Unexpected Application Error!", { exact: true })).toHaveCount(0);
        await page.getByRole("button", { name: refresh, exact: true }).press("Enter");
        await expect(page.getByRole("heading", { name: "Recovered card route" })).toBeVisible();
        await expect(page.getByRole("alert")).toHaveCount(0);
    });
}
