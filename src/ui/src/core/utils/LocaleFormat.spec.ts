import { expect, test } from "@playwright/test";

test("existing relative-time hook updates immediately when account language changes", async ({ page }) => {
    await page.addInitScript(() => localStorage.setItem("lang", "en-US"));
    await page.goto("/src/core/utils/LocaleFormat.fixture.html");
    await expect(page.getByTestId("relative")).toHaveText("5 minutes ago");
    for (const [locale, relative] of [
        ["ko-KR", "5분 전"],
        ["ja-JP", "5 分前"],
        ["zh-CN", "5分钟前"],
        ["en-US", "5 minutes ago"],
    ]) {
        await page.getByRole("button", { name: locale, exact: true }).click();
        await expect(page.getByTestId("relative")).toHaveText(relative, { timeout: 5000 });
        await expect(page.locator("html")).toHaveAttribute("lang", locale);
    }
});

test("calendar and duration follow all four account languages without remount", async ({ page }) => {
    await page.addInitScript(() => localStorage.setItem("lang", "en-US"));
    await page.goto("/src/core/utils/LocaleFormat.fixture.html");
    for (const [locale, month, done, duration] of [
        ["ko-KR", "10월", "완료", "1시간 2분 3초"],
        ["ja-JP", "10月", "完了", "1h 2m 3s"],
        ["zh-CN", "十月", "完成", "1小时 2分钟 3秒"],
        ["en-US", "October", "Done", "1h 2m 3s"],
    ]) {
        await page.getByRole("button", { name: locale, exact: true }).click();
        await expect(page.getByTestId("calendar").getByRole("button", { name: month, exact: true })).toBeVisible();
        await expect(page.getByTestId("calendar").getByRole("button", { name: done, exact: true })).toBeVisible();
        await expect(page.getByTestId("duration")).toHaveText(duration);
        await expect(page.getByTestId("count")).toHaveText("12,345");
        const overdue = {
            "ko-KR": ["1일 초과", "2일 초과"],
            "ja-JP": ["1日超過", "2日超過"],
            "zh-CN": ["已逾期1天", "已逾期2天"],
            "en-US": ["Overdue by 1 day", "Overdue by 2 days"],
        };
        await expect(page.getByTestId("overdue-one")).toHaveText(overdue[locale as keyof typeof overdue][0]);
        await expect(page.getByTestId("overdue-other")).toHaveText(overdue[locale as keyof typeof overdue][1]);
    }
});

test("shared accessible UI labels update with the account language", async ({ page }) => {
    await page.addInitScript(() => localStorage.setItem("lang", "en-US"));
    await page.goto("/src/core/utils/LocaleFormat.fixture.html");
    for (const [locale, breadcrumb, close, thoughts] of [
        ["ko-KR", "이동 경로", "닫기", "생각 펼치기..."],
        ["ja-JP", "パンくずリスト", "閉じる", "思考を表示..."],
        ["zh-CN", "导航路径", "关闭", "展开思考..."],
        ["en-US", "Breadcrumb", "Close", "Show thoughts..."],
    ]) {
        await page.getByRole("button", { name: locale, exact: true }).click();
        await expect(page.getByTestId("common-ui").getByRole("navigation", { name: breadcrumb })).toBeVisible();
        await expect(page.getByTestId("common-ui").getByRole("button", { name: close, exact: true })).toBeVisible();
        await expect(page.getByTestId("common-ui").getByRole("button", { name: thoughts })).toBeVisible();
    }
});

test("work island empty menu and drag prompt switch languages without navigation", async ({ page }) => {
    await page.addInitScript(() => localStorage.setItem("lang", "en-US"));
    await page.goto("/src/core/utils/LocaleFormat.fixture.html");
    for (const [locale, work, empty, all, drop] of [
        ["ko-KR", "내 작업", "실행 중인 작업이 없습니다.", "모든 작업 보기", "작업을 끌어놓아 시작"],
        ["ja-JP", "自分の作業", "実行中の作業はありません。", "すべての作業を表示", "ドロップして作業を開始"],
        ["zh-CN", "我的工作", "没有正在进行的工作。", "查看所有工作", "拖放以开始工作"],
        ["en-US", "My Work", "No work is running.", "View all work", "Drop to start work"],
    ]) {
        await page.getByRole("button", { name: locale, exact: true }).click();
        await page.getByTestId("work-island").getByRole("button", { name: work, exact: true }).click();
        await expect(page.getByText(empty, { exact: true })).toBeVisible();
        await expect(page.getByRole("button", { name: all, exact: true })).toBeVisible();
        await page.keyboard.press("Escape");
        await page.getByRole("checkbox", { name: "fixture dragging" }).check();
        await expect(page.getByTestId("work-island").getByText(drop, { exact: true })).toBeVisible();
        await page.getByRole("checkbox", { name: "fixture dragging" }).uncheck();
    }
});
