import { expect, test } from "@playwright/test";

const touch = (x: number) => ({
    identifier: 1,
    clientX: x,
    clientY: 60,
    pageX: x,
    pageY: 60,
    screenX: x,
    screenY: 60,
    radiusX: 1,
    radiusY: 1,
    rotationAngle: 0,
    force: 1,
});

test("a held touch scrolls a long board at either horizontal edge", async ({ page }) => {
    await page.goto("/src/pages/BoardPage/components/board/BoardTouchDnd.fixture.html");
    const board = page.locator("#board");
    await board.dispatchEvent("touchstart", { touches: [touch(318)], changedTouches: [touch(318)] });
    await expect.poll(() => board.evaluate((element) => element.scrollLeft)).toBeGreaterThan(80);

    await board.dispatchEvent("touchmove", { touches: [touch(160)], changedTouches: [touch(160)] });
    const centered = await board.evaluate((element) => element.scrollLeft);
    await page.waitForTimeout(100);
    expect(await board.evaluate((element) => element.scrollLeft)).toBe(centered);

    await board.dispatchEvent("touchmove", { touches: [touch(2)], changedTouches: [touch(2)] });
    await expect.poll(() => board.evaluate((element) => element.scrollLeft)).toBeLessThan(centered - 40);
    await board.dispatchEvent("touchend", { touches: [], changedTouches: [touch(2)] });
});

test("dropping on an empty column emits zero-based order", async ({ page }) => {
    await page.goto("/src/pages/BoardPage/components/board/BoardTouchDnd.fixture.html");
    const board = page.locator("#board");
    await board.dispatchEvent("touchstart", { touches: [touch(160)], changedTouches: [touch(160)] });
    await board.dispatchEvent("touchend", { touches: [], changedTouches: [touch(160)] });
    await expect(page.locator("#empty-column")).toHaveAttribute("data-drop-order", "0");
});
