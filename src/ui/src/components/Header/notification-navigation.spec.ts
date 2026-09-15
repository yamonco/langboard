import { expect, test } from "@playwright/test";

for (const width of [390, 1440]) {
    test(`notification navigation preserves each destination at viewport ${width}`, async ({ page }) => {
        await page.setViewportSize({ width, height: 900 });
        await page.goto("/src/components/Header/notification-navigation.fixture.html");
        for (const target of ["card", "wiki", "project"]) {
            await page.getByRole("button", { name: "Notifications", exact: true }).click();
            await page.getByRole("button", { name: `Open ${target}`, exact: true }).click();
            await expect(page.getByRole("button", { name: "Cancel", exact: true })).toHaveCount(0);
            await expect(page.getByRole("dialog", { name: `Destination ${target}` })).toBeVisible();
            await expect(page.getByRole("button", { name: "Destination action" })).toBeFocused();
            await page.getByRole("button", { name: "Notifications", exact: true }).click();
            // A modal popover temporarily hides the existing destination from the accessibility tree, but must not unmount it.
            await expect(page.getByRole("dialog", { name: `Destination ${target}`, includeHidden: true })).toHaveCount(1);
            await page.getByRole("button", { name: "Cancel", exact: true }).click();
            await expect(page.getByRole("dialog", { name: `Destination ${target}` })).toBeVisible();
            await page.getByRole("button", { name: "Close destination" }).click();
        }
        await page.getByRole("button", { name: "Notifications", exact: true }).click();
        await page.getByRole("button", { name: "Cancel", exact: true }).click();
        await expect(page.getByRole("button", { name: "Notifications", exact: true })).toBeFocused();
        await expect(page.getByRole("dialog")).toHaveCount(0);
        await page.getByRole("button", { name: "Notifications", exact: true }).click();
        await page.getByRole("button", { name: "Open card", exact: true }).click();
        await page.getByRole("button", { name: "Other navigation", exact: true }).click();
        await expect(page.getByRole("dialog")).toHaveCount(0);
    });
}
