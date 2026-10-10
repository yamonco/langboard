import { expect, test } from "@playwright/test";
const png = Buffer.from("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/l9sAAAAASUVORK5CYII=", "base64");
const fixture = "/src/components/CachedImage/protected-image.fixture.html";
test("native image uses API headers, no srcset bypass, and revokes blob on unmount", async ({ page }) => {
    let reads = 0;
    await page.route("**/file/encrypted/card_attachment/*.png", async (route) => {
        reads++;
        expect(route.request().headers().authorization).toBe("Bearer fixture-token");
        await route.fulfill({ contentType: "image/png", body: png });
    });
    await page.goto(fixture);
    await page.evaluate(async () => {
        const apiPath = "/src/core/helpers/Api.ts";
        const { api } = await import(apiPath);
        api.defaults.headers.common.Authorization = "Bearer fixture-token";
    });
    await page.getByText("Show", { exact: true }).click();
    const image = page.getByAltText("attachment");
    await expect(image).toHaveAttribute("src", /^blob:/);
    expect(await image.getAttribute("srcset")).toBeNull();
    const blob = (await image.getAttribute("src"))!;
    await page.getByText("Hide", { exact: true }).click();
    await expect(image).toHaveCount(0);
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
    expect(reads).toBe(1);
});
test("denial does not display raw protected URLs", async ({ page }) => {
    await page.route("**/file/encrypted/card_attachment/*.png", (route) => route.fulfill({ status: 404 }));
    await page.goto(fixture);
    await page.getByText("Show", { exact: true }).click();
    await expect(page.getByAltText("attachment")).toHaveCount(0);
    await page.getByText("Next", { exact: true }).click();
    await expect(page.getByAltText("attachment")).toHaveCount(0);
});
test("external image URLs never receive native authentication", async ({ page }) => {
    await page.route("https://external.example.invalid/**", async (route) => {
        expect(route.request().headers().authorization).toBeUndefined();
        await route.fulfill({ contentType: "image/png", body: png });
    });
    await page.goto(fixture);
    await page.getByText("External", { exact: true }).click();
    await page.getByText("Show", { exact: true }).click();
    await expect(page.getByAltText("attachment")).toHaveAttribute("src", /^https:\/\/external/);
});
test("logout removes mounted protected pixels and revokes their object URL", async ({ page }) => {
    let denied = false;
    await page.route("**/file/encrypted/card_attachment/*.png", (route) =>
        route.fulfill(denied ? { status: 404 } : { contentType: "image/png", body: png })
    );
    await page.goto(fixture);
    await page.getByText("Show", { exact: true }).click();
    const image = page.getByAltText("attachment");
    await expect(image).toHaveAttribute("src", /^blob:/);
    const blob = (await image.getAttribute("src"))!;
    denied = true;
    await page.evaluate(async () => {
        const authPath = "/src/core/stores/AuthStore.ts";
        const { getAuthStore } = await import(authPath);
        getAuthStore().removeToken();
    });
    await expect(image).toHaveCount(0);
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
});
test("cancelled late image cannot replace the newly selected source", async ({ page }) => {
    let release!: () => void;
    const pending = new Promise<void>((resolve) => {
        release = resolve;
    });
    let started!: () => void;
    const requested = new Promise<void>((resolve) => {
        started = resolve;
    });
    await page.route("**/file/encrypted/card_attachment/one.png", async (route) => {
        started();
        await pending;
        await route.fulfill({ contentType: "image/png", body: png }).catch(() => {});
    });
    await page.route("**/file/encrypted/card_attachment/two.png", (route) => route.fulfill({ status: 404 }));
    await page.goto(fixture);
    await page.getByText("Show", { exact: true }).click();
    await requested;
    const next = page.waitForResponse((response) => response.url().endsWith("two.png"));
    await page.getByText("Next", { exact: true }).click();
    await next;
    release();
    await expect(page.getByAltText("attachment")).toHaveCount(0);
});
