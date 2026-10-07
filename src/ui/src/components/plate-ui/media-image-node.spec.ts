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

test("Plate inline and preview authenticate protected images without changing persisted URLs", async ({ page }) => {
    const imageBody = `<svg xmlns="http://www.w3.org/2000/svg" width="900" height="600"><rect width="900" height="600" fill="teal"/></svg>`;
    let reads = 0;
    let denied = false;
    await page.route("**/file/encrypted/card_attachment/proof.png", async (route) => {
        reads++;
        expect(route.request().headers().authorization).toBe("Bearer fixture-token");
        await route.fulfill(denied ? { status: 404 } : { contentType: "image/svg+xml", body: imageBody });
    });
    await page.goto("/src/components/plate-ui/media-image-node.fixture.html");
    await page.evaluate(async () => {
        const apiPath = "/src/core/helpers/Api.ts";
        const { api } = await import(apiPath);
        api.defaults.headers.common.Authorization = "Bearer fixture-token";
        sessionStorage.setItem("fixture-auth", "1");
    });
    await page.goto("/src/components/plate-ui/media-image-node.fixture.html?protected");
    const inline = page.locator("[data-dynamic-image-fixture] [data-slate-editor] img");
    await expect(inline.first()).toHaveAttribute("src", /^blob:/);
    await inline.last().click();
    const preview = page.locator("div.fixed.left-0.top-0:not(.hidden) img");
    await expect(preview).toHaveAttribute("src", /^blob:/);
    const blob = (await preview.getAttribute("src"))!;
    await preview.click();
    await expect(preview).toHaveCSS("cursor", "zoom-out");
    await page.keyboard.press("Escape");
    await expect(preview).toHaveCount(0);
    expect(
        await page.evaluate(async (url) => {
            try {
                await fetch(url);
                return true;
            } catch {
                return false;
            }
        }, blob)
    ).toBe(false);
    expect(await page.evaluate(() => (window as unknown as { fixtureEditor: { children: { url: string }[] } }).fixtureEditor.children[0].url)).toBe(
        "/file/encrypted/card_attachment/proof.png"
    );
    await inline.first().dblclick();
    await expect(preview).toHaveAttribute("src", /^blob:/);
    denied = true;
    await page.evaluate(async () => {
        const authPath = "/src/core/stores/AuthStore.ts";
        const { getAuthStore } = await import(authPath);
        getAuthStore().removeToken();
    });
    await expect(preview).not.toHaveAttribute("src", /.+/);
    await expect(inline.first()).not.toHaveAttribute("src", /.+/);
    expect(reads).toBeGreaterThanOrEqual(4);
});
