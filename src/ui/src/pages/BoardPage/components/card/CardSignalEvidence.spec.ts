import { test, expect } from "@playwright/test";
const path = "/src/pages/BoardPage/components/card/CardSignalEvidence.fixture.html";
for (const width of [1440, 390])
    test(`explicit link and unlink ${width}`, async ({ page }) => {
        await page.setViewportSize({ width, height: 850 });
        await page.goto(path + "?empty");
        expect(await page.evaluate(() => (window as unknown as { evidenceCalls: unknown[] }).evidenceCalls.length)).toBe(0);
        await page.getByRole("button", { name: "Check evidence", exact: true }).click();
        await expect(page.getByText("No linked checks")).toBeVisible();
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
        await expect(page.getByText("No linked checks")).toBeVisible();
    });
test("revoked evidence retains unlink and readonly hides writes", async ({ page }) => {
    await page.goto(path + "?revoked");
    await page.getByRole("button", { name: "Check evidence", exact: true }).click();
    await expect(page.getByText("Unavailable", { exact: true })).toBeVisible();
    await page.getByRole("button", { name: "Unlink", exact: true }).click();
    await expect(page.getByText("No linked checks")).toBeVisible();
    await page.goto(path + "?readonly");
    await page.getByRole("button", { name: "Check evidence", exact: true }).click();
    await expect(page.getByText("Passed · #55")).toBeVisible();
    await expect(page.getByRole("button", { name: "Unlink", exact: true })).toHaveCount(0);
    await expect(page.getByRole("button", { name: "Link a check", exact: true })).toHaveCount(0);
});
test("failed mutation clears optimistic evidence and card switch resets", async ({ page }) => {
    await page.goto(path + "?error");
    await page.getByRole("button", { name: "Check evidence", exact: true }).click();
    await expect(page.getByText("Passed · #55")).toBeVisible();
    await page.getByRole("button", { name: "Unlink", exact: true }).click();
    await expect(page.getByRole("alert")).toBeVisible();
    await expect(page.getByText("Passed · #55")).toHaveCount(0);
    await page.getByRole("button", { name: "Refresh evidence" }).click();
    await expect(page.getByText("Passed · #55")).toBeVisible();
    await page.getByRole("button", { name: "Switch card" }).click();
    await expect(page.getByRole("button", { name: "Check evidence", exact: true })).toHaveAttribute("aria-expanded", "false");
    await expect(page.getByText("Passed · #55")).toHaveCount(0);
});

test("Korean mobile evidence labels", async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 850 });
    await page.goto(path + "?lang=ko-KR");
    await page.getByRole("button", { name: "체크 증거", exact: true }).click();
    await expect(page.getByText("통과 · #55")).toBeVisible();
    await expect(page.getByRole("button", { name: "연결 해제", exact: true })).toBeVisible();
    await expect(page.getByText("증거 연결은 카드 승인이나 완료를 의미하지 않습니다.")).toBeVisible();
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    await page.screenshot({ path: "test-results/card-evidence-ko-390.png", fullPage: true });
});
