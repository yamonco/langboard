import { expect, test } from "@playwright/test";

for (const width of [390, 1440]) {
    test(`large images retain their aspect ratio within a comment at viewport ${width}`, async ({ page }) => {
        await page.setViewportSize({ width, height: 900 });
        await page.goto("/src/components/plate-ui/media-image-node.fixture.html");
        const images = page.locator("[data-slate-editor] img");
        await expect(images).toHaveCount(2);
        for (const image of await images.all()) {
            await expect.poll(() => image.evaluate((node: HTMLImageElement) => node.naturalWidth)).toBeGreaterThan(0);
            const size = await image.evaluate((node: HTMLImageElement) => ({
                width: node.getBoundingClientRect().width,
                height: node.getBoundingClientRect().height,
                naturalRatio: node.naturalWidth / node.naturalHeight,
                availableWidth: node.closest("[data-slate-editor]")!.getBoundingClientRect().width,
            }));
            expect(size.width).toBeGreaterThan(0);
            expect(size.width).toBeLessThanOrEqual(size.availableWidth + 1);
            expect(size.width / size.height).toBeCloseTo(size.naturalRatio, 2);
            expect(size.height).toBeLessThanOrEqual(384);
            await image.click();
            const preview = page.locator("div.fixed:not(.hidden)");
            await expect(preview).toHaveCount(1);
            await expect(preview.locator("img")).toBeVisible();
            await preview.click({ position: { x: 3, y: 3 } });
            await expect(preview).toHaveCount(0);
            await image.focus();
            await image.press("Enter");
            await expect(preview).toHaveCount(1);
            await preview.click({ position: { x: 3, y: 3 } });
        }
    });
}
