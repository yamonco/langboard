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

test("relationship classifications translate while user relation names remain unchanged", async ({ page }) => {
    await page.addInitScript(() => localStorage.setItem("lang", "en-US"));
    await page.goto("/src/core/utils/LocaleFormat.fixture.html");
    for (const [locale, composition, dependencies, references] of [
        ["ko-KR", "구성", "실행 의존성", "참고"],
        ["ja-JP", "構成", "実行の依存関係", "参照"],
        ["zh-CN", "组成", "执行依赖", "参考"],
        ["en-US", "Composition", "Execution dependencies", "References"],
    ]) {
        await page.getByRole("button", { name: locale, exact: true }).click();
        const picker = page.getByTestId("relationship-picker");
        for (const label of [composition, dependencies, references]) await expect(picker.getByText(label, { exact: true })).toBeVisible();
        for (const semantic of ["contains", "blocks", "references"])
            await expect(picker.getByRole("button", { name: `User ${semantic}`, exact: true })).toBeVisible();
    }
});

test("card diagram fallback and source label translate without altering source content", async ({ page }) => {
    await page.addInitScript(() => localStorage.setItem("lang", "en-US"));
    await page.goto("/src/core/utils/LocaleFormat.fixture.html");
    for (const [locale, source, unavailable] of [
        ["ko-KR", "소스", "mermaid 다이어그램 미리보기를 사용할 수 없습니다."],
        ["ja-JP", "ソース", "mermaidダイアグラムのプレビューは利用できません。"],
        ["zh-CN", "源代码", "无法预览mermaid图表。"],
        ["en-US", "source", "mermaid diagram preview is unavailable."],
    ]) {
        await page.getByRole("button", { name: locale, exact: true }).click();
        const blocks = page.getByTestId("content-blocks");
        await expect(blocks.locator("summary")).toHaveText(`mermaid ${source}`);
        await expect(blocks.getByText(unavailable, { exact: true })).toBeVisible();
        await expect(blocks.locator("code")).toHaveText("graph TD; User--&gt;Data;");
    }
});

test("code language choices translate and search without rewriting source", async ({ page }) => {
    await page.goto("/src/core/utils/LocaleFormat.fixture.html");
    for (const [locale, plain, auto] of [
        ["ko-KR", "일반 텍스트", "자동"],
        ["ja-JP", "プレーンテキスト", "自動"],
        ["zh-CN", "纯文本", "自动"],
        ["en-US", "Plain Text", "Auto"],
    ]) {
        await page.getByRole("button", { name: locale, exact: true }).click();
        const editor = page.getByTestId("code-editor");
        await expect(editor.getByRole("combobox")).toHaveText(plain);
        await editor.getByRole("combobox").click();
        const search = page.getByRole("dialog").getByRole("combobox");
        await search.fill(auto);
        await expect(page.getByRole("option", { name: auto, exact: true })).toBeVisible();
        await search.fill("plaintext");
        await page.getByRole("option", { name: plain, exact: true }).click();
        await expect(editor.locator("pre code")).toHaveText("const user = 1;");
    }
});

test("board counts and stale days use locale interpolation and singular grammar", async ({ page }) => {
    await page.addInitScript(() => localStorage.setItem("lang", "en-US"));
    await page.goto("/src/core/utils/LocaleFormat.fixture.html");
    for (const [locale, stageLabel] of [
        ["ko-KR", "워크플로우 단계: User stage"],
        ["ja-JP", "ワークフローステージ: User stage"],
        ["zh-CN", "工作流阶段：User stage"],
        ["en-US", "Workflow stage: User stage"],
    ]) {
        await page.getByRole("button", { name: locale, exact: true }).click();
        await expect(page.getByTestId("workflow-stage-label")).toHaveText(stageLabel);
        await expect(page.getByTestId("graph-counts")).toContainText("1,234");
        await expect(page.getByTestId("graph-counts")).toContainText("2,345");
        await expect(page.getByTestId("checklist-counts")).toContainText("1,234");
        await expect(page.getByTestId("checklist-counts")).toContainText("2,345");
        await expect(page.getByTestId("stale-many")).toContainText("1,234");
    }
    await expect(page.getByTestId("stale-one")).toHaveText("Unchanged for 1 day");
    await expect(page.getByTestId("stale-many")).toHaveText("Unchanged for 1,234 days");
});

test("card outline counts follow language switches and keep user content unchanged", async ({ page }) => {
    await page.addInitScript(() => localStorage.setItem("lang", "en-US"));
    await page.goto("/src/core/utils/LocaleFormat.fixture.html");
    for (const [locale, checklist, comments] of [
        ["ko-KR", "체크리스트", "댓글"],
        ["ja-JP", "チェックリスト", "コメント"],
        ["zh-CN", "检查清单", "评论"],
        ["en-US", "Checklists", "Comments"],
    ]) {
        await page.getByRole("button", { name: locale, exact: true }).click();
        const outline = page.getByTestId("outline-counts");
        await expect(outline.getByRole("button", { name: `${checklist}1,234/2,345`, exact: true })).toBeVisible();
        await expect(outline.getByRole("button", { name: `${comments}1,234`, exact: true })).toBeVisible();
        await expect(outline.getByText("User card title", { exact: true })).toBeVisible();
    }
});

test("pagination and numeric messages format quantities in all supported languages", async ({ page }) => {
    await page.goto("/src/core/utils/LocaleFormat.fixture.html");
    for (const locale of ["ko-KR", "ja-JP", "zh-CN", "en-US"]) {
        await page.getByRole("button", { name: locale, exact: true }).click();
        await expect(page.getByTestId("pagination-counts")).toContainText("1,234");
        await expect(page.getByTestId("pagination-counts")).toContainText("2,345");
        for (const id of ["numeric-notification", "numeric-activity", "numeric-approval"]) await expect(page.getByTestId(id)).toContainText("1,234");
    }
});

test("large description rail formats grouped ranges and accessible totals", async ({ page }) => {
    await page.goto("/src/core/utils/LocaleFormat.fixture.html");
    for (const locale of ["ko-KR", "ja-JP", "zh-CN", "en-US"]) {
        await page.getByRole("button", { name: locale, exact: true }).click();
        const lastMarker = page.getByTestId("description-rail").getByRole("button").last();
        await expect(lastMarker).toHaveAttribute("aria-label", /1,234/);
        await lastMarker.focus();
        await expect(page.getByText("1,223–1,234", { exact: true })).toBeVisible();
        await expect(page.getByText("User block 1222", { exact: true })).toBeVisible();
        await page.getByRole("button", { name: locale, exact: true }).focus();
    }
});

test("remaining permission, event, work, reader and tool counts use locale grouping", async ({ page }) => {
    await page.goto("/src/core/utils/LocaleFormat.fixture.html");
    for (const locale of ["ko-KR", "ja-JP", "zh-CN", "en-US"]) {
        await page.getByRole("button", { name: locale, exact: true }).click();
        const messages = page.getByTestId("remaining-counts").locator("span");
        await expect(messages).toHaveCount(7);
        for (const message of await messages.all()) await expect(message).toContainText("1,234");
    }
});
