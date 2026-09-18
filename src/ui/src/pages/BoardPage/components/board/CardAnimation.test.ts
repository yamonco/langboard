import assert from "node:assert/strict";
import test from "node:test";
import {
    CARD_ANIMATION_DURATION_MS,
    CARD_ANIMATION_EASING,
    cardOpenAnimation,
    closedTransform,
} from "./CardAnimation.ts";

test("animation duration is in the 160-220ms spec range", () => {
    assert.ok(CARD_ANIMATION_DURATION_MS >= 160, `too fast: ${CARD_ANIMATION_DURATION_MS}`);
    assert.ok(CARD_ANIMATION_DURATION_MS <= 220, `too slow: ${CARD_ANIMATION_DURATION_MS}`);
});

test("easing is a smooth ease-out curve", () => {
    assert.equal(CARD_ANIMATION_EASING, "cubic-bezier(0.2, 0.8, 0.2, 1)");
});

test("animation string includes transform and opacity", () => {
    const anim = cardOpenAnimation();
    assert.ok(anim.includes("transform"));
    assert.ok(anim.includes("opacity"));
    assert.ok(anim.includes(`${CARD_ANIMATION_DURATION_MS}ms`));
    assert.ok(!anim.includes("width"));
    assert.ok(!anim.includes("height"));
    assert.ok(!anim.includes("top"));
    assert.ok(!anim.includes("left"));
});

test("closedTransform computes scale and translate from rects", () => {
    const cardRect = { left: 100, top: 200, width: 300, height: 150 } as DOMRect;
    const targetRect = { left: 0, top: 0, width: 600, height: 400 } as DOMRect;
    const transform = closedTransform(cardRect, targetRect);
    assert.ok(transform.includes("translate("));
    assert.ok(transform.includes("scale("));
    assert.ok(transform.includes("0.5"), "scaleX should be 300/600");
});

test("closedTransform handles zero-size target gracefully", () => {
    const cardRect = { left: 0, top: 0, width: 100, height: 50 } as DOMRect;
    const targetRect = { left: 0, top: 0, width: 0, height: 0 } as DOMRect;
    const transform = closedTransform(cardRect, targetRect);
    assert.ok(transform.includes("translate("));
    assert.ok(transform.includes("scale("));
    assert.ok(!transform.includes("NaN"));
    assert.ok(!transform.includes("Infinity"));
});
