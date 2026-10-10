import { expect, test } from "@playwright/test";
import { readFileSync } from "node:fs";
for (const viewport of [
    { width: 1280, height: 720 },
    { width: 390, height: 844 },
]) {
    test(`commands retain board route and focus visible pending panel at ${viewport.width}px`, async ({ page }) => {
        await page.setViewportSize(viewport);
        await page.goto("/src/pages/DashboardPage/components/command-context.fixture.html");
        for (const [label, mode] of [
            ["Changes", "changes"],
            ["Relations", "relations"],
            ["My Work", "my-work"],
            ["Changes", "changes"],
        ]) {
            await page.getByRole("button", { name: "Open palette", exact: true }).press("Enter");
            const input = page.getByRole("combobox", { name: "Command palette", exact: true });
            await input.fill(label);
            await input.press("End");
            await input.press("Enter");
            const target = page.getByRole(viewport.width < 768 ? "complementary" : "region", { name: mode, exact: true });
            await expect(target).toBeFocused();
            if (viewport.width < 768) {
                await target.press("Tab");
                await expect(page.getByRole("button", { name: "Close panel", exact: true })).toBeFocused();
            }
            await expect(page.getByTestId("route")).toHaveText("/board/fixture");
            await expect(page.getByText("Panel content pending", { exact: true })).toBeVisible();
        }
        await page.getByRole("button", { name: "Open palette", exact: true }).press("Enter");
        await page.getByRole("combobox", { name: "Command palette", exact: true }).press("Escape");
        await expect(page.getByRole("button", { name: "Open palette", exact: true })).toBeFocused();
    });
}

for (const language of ["en-US", "ko-KR", "ja-JP", "zh-CN"]) {
    const labels = JSON.parse(readFileSync(new URL(`../../../assets/locales/${language}/dashboard.json`, import.meta.url), "utf8"));
    test(`visible command labels are searchable in ${language}`, async ({ page }) => {
        await page.addInitScript((lang) => localStorage.setItem("lang", lang), language);
        await page.goto("/src/pages/DashboardPage/components/command-context.fixture.html");
        await page.getByRole("button", { name: "Open palette", exact: true }).click();
        const input = page.getByRole("combobox", { name: labels["Command palette"], exact: true });
        for (const key of ["New card", "New project", "Toggle sidebar", "My Work", "Changes", "Relations"]) {
            const label = labels[key];
            await input.fill(label);
            await expect(page.getByRole("option", { name: label, exact: true })).toBeVisible();
        }
        await input.fill(labels.Changes);
        await input.press("Enter");
        await expect(page.getByRole("region", { name: "changes", exact: true })).toBeFocused();
        await expect(page.getByTestId("route")).toHaveText("/board/fixture");
    });
}
