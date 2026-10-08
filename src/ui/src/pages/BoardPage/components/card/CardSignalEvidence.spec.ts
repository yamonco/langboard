import { test, expect } from "@playwright/test";
const path = "/src/pages/BoardPage/components/card/CardSignalEvidence.fixture.html";
for (const width of [1920, 390])
    test(`explicit link and unlink ${width}`, async ({ page }) => {
        await page.setViewportSize({ width, height: 850 });
        await page.goto(path + "?empty");
        expect(await page.evaluate(() => (window as unknown as { evidenceCalls: unknown[] }).evidenceCalls.length)).toBe(0);
        await page.getByRole("button", { name: "Signal evidence", exact: true }).click();
        await expect(page.getByText("No linked evidence")).toBeVisible();
        await page.getByRole("button", { name: "Link a check", exact: true }).click();
        await page.getByRole("combobox", { name: "Repository" }).selectOption("resource");
        await page.getByRole("button", { name: "#55" }).click();
        await expect(page.getByText("Passed · #55")).toBeVisible();
        const calls = await page.evaluate(() => (window as unknown as { evidenceCalls: { method: string; data: unknown }[] }).evidenceCalls);
        expect(calls.find((row) => row.method === "post")?.data).toEqual({
            connection_uid: "connection",
            resource_uid: "resource",
            signal_uid: "signal",
            source_change_seq: 7,
            expected_revision: null,
        });
        expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
        await page.screenshot({ path: `test-results/card-evidence-${width}.png`, fullPage: true });
        await page.getByRole("button", { name: "Unlink", exact: true }).click();
        await expect(page.getByText("No linked evidence")).toBeVisible();
    });
test("revoked evidence retains unlink and readonly hides writes", async ({ page }) => {
    await page.goto(path + "?revoked");
    await page.getByRole("button", { name: "Signal evidence", exact: true }).click();
    await expect(page.getByText("Unavailable", { exact: true })).toBeVisible();
    await page.getByRole("button", { name: "Unlink", exact: true }).click();
    await expect(page.getByText("No linked evidence")).toBeVisible();
    await page.goto(path + "?readonly");
    await page.getByRole("button", { name: "Signal evidence", exact: true }).click();
    await expect(page.getByText("Passed · #55")).toBeVisible();
    await expect(page.getByRole("button", { name: "Unlink", exact: true })).toHaveCount(0);
    await expect(page.getByRole("button", { name: "Link a check", exact: true })).toHaveCount(0);
});
test("failed mutation clears optimistic evidence and card switch resets", async ({ page }) => {
    await page.goto(path + "?error");
    await page.getByRole("button", { name: "Signal evidence", exact: true }).click();
    await expect(page.getByText("Passed · #55")).toBeVisible();
    await page.getByRole("button", { name: "Unlink", exact: true }).click();
    await expect(page.getByRole("alert")).toBeVisible();
    await expect(page.getByText("Passed · #55")).toHaveCount(0);
    await page.getByRole("button", { name: "Refresh evidence" }).click();
    await expect(page.getByText("Passed · #55")).toBeVisible();
    await page.getByRole("button", { name: "Switch card" }).click();
    await expect(page.getByRole("button", { name: "Signal evidence", exact: true })).toHaveAttribute("aria-expanded", "false");
    await expect(page.getByText("Passed · #55")).toHaveCount(0);
});

test("Korean mobile evidence labels", async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 850 });
    await page.goto(path + "?lang=ko-KR");
    await page.getByRole("button", { name: "신호 증거", exact: true }).click();
    await expect(page.getByText("통과 · #55")).toBeVisible();
    await expect(page.getByRole("button", { name: "연결 해제", exact: true })).toBeVisible();
    await expect(page.getByText("증거 연결은 카드 승인이나 완료를 의미하지 않습니다.")).toBeVisible();
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    await page.screenshot({ path: "test-results/card-evidence-ko-390.png", fullPage: true });
});

test("open evidence coalesces signal burst and refreshes after reconnect", async ({ page }) => {
    await page.goto(path);
    await page.getByRole("button", { name: "Signal burst" }).click();
    expect(await page.evaluate(() => (window as unknown as { evidenceCalls: unknown[] }).evidenceCalls.length)).toBe(0);
    await page.getByRole("button", { name: "Signal evidence", exact: true }).click();
    await expect(page.getByText("Failed · #55")).toBeVisible();
    const before = await page.evaluate(() => (window as unknown as { evidenceCalls: unknown[] }).evidenceCalls.length);
    await page.getByRole("button", { name: "Signal burst" }).click();
    await expect.poll(() => page.evaluate(() => (window as unknown as { evidenceCalls: unknown[] }).evidenceCalls.length)).toBe(before + 1);
    await page.getByRole("button", { name: "Reconnect" }).click();
    await expect.poll(() => page.evaluate(() => (window as unknown as { evidenceCalls: unknown[] }).evidenceCalls.length)).toBe(before + 2);
    await page.getByRole("button", { name: "Return to window" }).click();
    await expect.poll(() => page.evaluate(() => (window as unknown as { evidenceCalls: unknown[] }).evidenceCalls.length)).toBe(before + 3);
    await page.getByRole("button", { name: "Edit card" }).click();
    await expect.poll(() => page.evaluate(() => (window as unknown as { evidenceCalls: unknown[] }).evidenceCalls.length)).toBe(before + 4);
    await page.getByRole("button", { name: "Signal evidence", exact: true }).click();
    await page.getByRole("button", { name: "Signal burst" }).click();
    await page.getByRole("button", { name: "Reconnect" }).click();
    await page.getByRole("button", { name: "Return to window" }).click();
    await page.getByRole("button", { name: "Edit card" }).click();
    expect(await page.evaluate(() => (window as unknown as { evidenceCalls: unknown[] }).evidenceCalls.length)).toBe(before + 4);
});

for (const width of [1920, 390])
    test(`mixed card deployment evidence ${width}`, async ({ page }) => {
        await page.clock.install({ time: new Date("2026-10-08T00:30:00Z") });
        await page.setViewportSize({ width, height: 1000 });
        await page.goto(path + "?mixed");
        await page.getByRole("button", { name: "Signal evidence", exact: true }).click();
        await expect(page.getByText("Passed · #55")).toBeVisible();
        await expect(page.getByText("Dokploy · Passed", { exact: true })).toBeVisible();
        await expect(page.getByText("Customer API · Application", { exact: true })).toBeVisible();
        await expect(page.getByText("Customer stack · Compose", { exact: true })).toBeVisible();
        const deployment = page.getByText("Dokploy · Passed", { exact: true }).locator("../..");
        await expect(deployment).toContainText("Deployment succeeded · actual-application-deployment");
        await expect(deployment).not.toContainText("#actual");
        await expect(deployment).not.toContainText("aaaa");
        await expect(deployment.locator("time")).toHaveText("30 minutes ago");
        await expect(deployment.locator("time")).toHaveAttribute(
            "title",
            await page.evaluate(() =>
                new Intl.DateTimeFormat("en-US", { dateStyle: "medium", timeStyle: "medium" }).format(new Date("2026-10-08T00:00:00Z"))
            )
        );
        await page.getByRole("button", { name: "Link a check", exact: true }).click();
        await expect(page.getByRole("combobox", { name: "Repository" }).locator("option")).toHaveText(["Repository", "sample/repository"]);
        await page.screenshot({ path: `test-results/card-deployment-evidence-${width}.png`, fullPage: true });
        expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
        await deployment.locator("..").getByRole("button", { name: "Unlink", exact: true }).click();
        await expect(page.getByText("Dokploy · Passed", { exact: true })).toHaveCount(0);
        const calls = await page.evaluate(
            () => (window as unknown as { evidenceCalls: { method: string; url: string; data: unknown }[] }).evidenceCalls
        );
        expect(calls.find((row) => row.url.endsWith("/deployment-application/unlink"))?.data).toEqual({ expected_revision: 3 });
    });
test("mixed Korean evidence readonly and states", async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 1000 });
    for (const [state, label] of [
        ["queued", "대기 중"],
        ["running", "실행 중"],
        ["failed", "실패"],
        ["cancelled", "취소"],
        ["conflict", "결과 상충"],
        ["stale", "이전 카드의 증거"],
        ["unavailable", "조회 불가"],
    ]) {
        await page.goto(path + `?mixed&readonly&lang=ko-KR&state=${state}`);
        await page.getByRole("button", { name: "신호 증거", exact: true }).click();
        await expect(page.getByText(`Dokploy · ${label}`, { exact: true }).first()).toBeVisible();
        await expect(page.getByRole("button", { name: "연결 해제", exact: true })).toHaveCount(0);
        await expect(page.getByRole("button", { name: "체크 연결", exact: true })).toHaveCount(0);
    }
    await page.screenshot({ path: "test-results/card-deployment-evidence-ko-390.png", fullPage: true });
});
test("delayed mixed evidence discarded on card switch", async ({ page }) => {
    await page.goto(path + "?mixed&delayed");
    await page.getByRole("button", { name: "Signal evidence", exact: true }).click();
    await expect(page.getByRole("status")).toBeVisible();
    await page.getByRole("button", { name: "Switch card" }).click();
    await page.waitForTimeout(450);
    await expect(page.getByText("Dokploy · Passed", { exact: true })).toHaveCount(0);
    await expect(page.getByRole("button", { name: "Signal evidence", exact: true })).toHaveAttribute("aria-expanded", "false");
});

for (const width of [1920, 390])
    test(`GlitchTip truthful card observations and unlink ${width}`, async ({ page }) => {
        await page.clock.install({ time: new Date("2026-10-08T00:30:00Z") });
        await page.setViewportSize({ width, height: width === 1920 ? 1080 : 1000 });
        await page.goto(path + "?glitchtip&mixed");
        await page.getByRole("button", { name: "Signal evidence", exact: true }).click();
        for (const [id, state, outcome] of [
            [101, "Failed", "Unresolved"],
            [102, "Resolved", "Resolved"],
            [103, "Ignored", "Ignored"],
        ]) {
            const issue = page.getByText(`Issue ${id} · ${outcome}`, { exact: true }).locator("..");
            await expect(issue).toContainText(`GlitchTip · ${state}`);
            await expect(issue).toContainText("Customer errors · Project");
            await expect(issue.locator("time")).toHaveText("Observed at · 30 minutes ago");
            await expect(issue.locator("time")).toHaveAttribute("datetime", "2026-10-08T00:00:00Z");
            await expect(issue).not.toContainText("Passed");
            await expect(issue).not.toContainText("Deployment");
            await expect(issue).not.toContainText("aaaa");
        }
        await expect(page.getByText("Evidence does not approve or close this card.")).toBeVisible();
        await page.screenshot({ path: `test-results/glitchtip-card-${width}.png`, fullPage: true });
        expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
        expect(
            await page.evaluate(() =>
                (window as unknown as { evidenceCalls: { method: string }[] }).evidenceCalls.some((row) => row.method === "post")
            )
        ).toBe(false);
        await page
            .getByText("Issue 102 · Resolved", { exact: true })
            .locator("../../..")
            .getByRole("button", { name: "Unlink", exact: true })
            .click();
        await expect(page.getByText("Issue 102 · Resolved", { exact: true })).toHaveCount(0);
        expect(
            await page.evaluate(
                () =>
                    (window as unknown as { evidenceCalls: { url: string; data: unknown }[] }).evidenceCalls.find((row) =>
                        row.url.endsWith("/issue-resolved/unlink")
                    )?.data
            )
        ).toEqual({ expected_revision: 5 });
    });
test("GlitchTip stale conflict unavailable and current permission revocation", async ({ page }) => {
    for (const [state, label] of [
        ["stale", "Stale"],
        ["conflict", "Conflicting results"],
        ["unavailable", "Unavailable"],
    ]) {
        await page.goto(path + `?glitchtip&state=${state}`);
        await page.getByRole("button", { name: "Signal evidence", exact: true }).click();
        await expect(page.getByText(`GlitchTip · ${label}`, { exact: true }).first()).toBeVisible();
    }
    await page.goto(path + "?glitchtip");
    await page.getByRole("button", { name: "Signal evidence", exact: true }).click();
    await expect(page.getByText("Issue 101 · Unresolved", { exact: true })).toBeVisible();
    await page.getByRole("button", { name: "Revoke issue access", exact: true }).click();
    await expect(page.getByText("Issue 101 · Unresolved", { exact: true })).toHaveCount(0);
    await expect(page.getByText("Unavailable", { exact: true })).toHaveCount(3);
    await expect(page.getByRole("button", { name: "Unlink", exact: true })).toHaveCount(4);
    await page.getByRole("button", { name: "Remove edit access", exact: true }).click();
    await expect(page.getByRole("button", { name: "Unlink", exact: true })).toHaveCount(0);
    await expect(page.getByRole("button", { name: "Link a check", exact: true })).toHaveCount(0);
});
