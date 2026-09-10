import assert from "node:assert/strict";
import test from "node:test";
import { boardTouchAutoScrollDelta } from "./BoardTouchAutoScroll.ts";

test("long boards scroll only while the touch pointer is inside an edge zone", () => {
    assert.equal(boardTouchAutoScrollDelta(200, 0, 400), 0);
    assert.equal(boardTouchAutoScrollDelta(72, 0, 400), 0);
    assert.equal(boardTouchAutoScrollDelta(328, 0, 400), 0);
    assert.ok(boardTouchAutoScrollDelta(20, 0, 400) < 0);
    assert.ok(boardTouchAutoScrollDelta(380, 0, 400) > 0);
});

test("edge scrolling is bounded and accelerates toward either edge", () => {
    const nearLeft = boardTouchAutoScrollDelta(60, 0, 400);
    const farLeft = boardTouchAutoScrollDelta(0, 0, 400);
    const nearRight = boardTouchAutoScrollDelta(340, 0, 400);
    const farRight = boardTouchAutoScrollDelta(400, 0, 400);
    assert.ok(Math.abs(farLeft) > Math.abs(nearLeft));
    assert.ok(Math.abs(farRight) > Math.abs(nearRight));
    assert.equal(farLeft, -18);
    assert.equal(farRight, 18);
});

test("invalid or disabled viewports never scroll", () => {
    assert.equal(boardTouchAutoScrollDelta(100, 200, 100), 0);
    assert.equal(boardTouchAutoScrollDelta(0, 0, 400, 0), 0);
    assert.equal(boardTouchAutoScrollDelta(0, 0, 400, 72, 0), 0);
});
