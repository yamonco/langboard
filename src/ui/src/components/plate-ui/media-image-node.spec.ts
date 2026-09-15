import { expect, test } from "@playwright/test";

for (const width of [390, 1440]) {
    test(`static thumbnail uses the native viewer for extensionless images at viewport ${width}`, async ({ page }) => {
        await page.setViewportSize({ width, height: 900 });
        await page.goto("/src/components/plate-ui/media-image-node.fixture.html");
        await expect(page.locator("[data-thumbnail-fixture]")).toHaveCount(3);
        for (const thumbnail of await page.locator("[data-thumbnail-fixture]").all()) {
            const image = thumbnail.locator("img");
            await expect(image).toBeVisible();
            const height = await image.evaluate((node) => node.getBoundingClientRect().height);
            expect(height).toBeLessThanOrEqual(384);
            await thumbnail.getByRole("button").click();
            const preview = page.getByRole("dialog", { name: /^(editor\.)?Image$/ });
            await expect(preview.locator("img")).toBeVisible();
            const bounds = await preview
                .locator("img")
                .evaluate((node) => ({ width: node.getBoundingClientRect().width, height: node.getBoundingClientRect().height }));
            expect(bounds.width).toBeLessThanOrEqual(width - 32);
            expect(bounds.height).toBeLessThanOrEqual(836);
            await page.keyboard.press("ArrowUp");
            await expect(preview.locator("input").last()).toHaveValue("110");
            await page.keyboard.press("Escape");
            await expect(preview).toHaveCount(0);
            await expect(thumbnail).toBeVisible();
            await thumbnail.getByRole("button").focus();
            await page.keyboard.press("Space");
            await expect(preview.locator("img")).toBeVisible();
            await page.keyboard.press("Escape");
        }
    });
    test(`large images retain their aspect ratio within a comment at viewport ${width}`, async ({ page }) => {
        await page.setViewportSize({ width, height: 900 });
        await page.goto("/src/components/plate-ui/media-image-node.fixture.html");
        const images = page.locator("[data-dynamic-image-fixture] [data-slate-editor] img");
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
            const preview = page.locator("div.fixed.left-0.top-0:not(.hidden)");
            await expect(preview).toHaveCount(1);
            await expect(preview.locator("img")).toBeVisible();
            await page.keyboard.press("Escape");
            await expect(page.getByRole("dialog", { name: "Image card", exact: true })).toBeVisible();
            await expect(preview).toHaveCount(0);
            await image.click();
            await expect(preview).toHaveCount(1);
            await preview.click({ position: { x: 3, y: 3 } });
            await expect(preview).toHaveCount(0);
            await image.focus();
            await image.press("Enter");
            await expect(preview).toHaveCount(1);
            await preview.click({ position: { x: 3, y: 3 } });
        }
    });
}
