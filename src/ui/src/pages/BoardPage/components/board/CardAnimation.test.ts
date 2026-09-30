import assert from "node:assert/strict";
import test from "node:test";
import {
    CARD_ANIMATION_DURATION_MS,
    CARD_ANIMATION_EASING,
    cardOpenAnimation,
    captureCardOrigin,
    clearCardOpenAnimationSession,
    closedTransform,
    isRectCenterInside,
    markCardOpenAnimationPlayed,
    OPEN_REPLAY_SUPPRESSION_MS,
    shouldPlayCardOpenAnimation,
    takeCardOrigin,
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
    assert.equal(transform, "translate(-50px, 75px) scale(0.5, 0.375)");
});

test("card origin is keyed, copied, and consumed once", () => {
    const rect = { left: 25, top: 50, width: 180, height: 80 } as DOMRect;
    captureCardOrigin("board-a", "card-a", rect);
    assert.deepEqual(takeCardOrigin("board-a", "card-a"), { left: 25, top: 50, width: 180, height: 80 });
    assert.equal(takeCardOrigin("board-a", "card-a"), null);
    captureCardOrigin("board-a", "card-a", rect);
    assert.equal(takeCardOrigin("board-a", "card-b"), null);
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

test("close origin must remain visible inside both viewport and board scrollport", () => {
    const card = { left: 1709, top: 201, width: 294, height: 114 } as DOMRect;
    const viewport = { left: 0, top: 0, width: 1686, height: 900 } as DOMRect;
    assert.equal(isRectCenterInside(card, viewport), false);
    const visibleCard = { left: 500, top: 201, width: 294, height: 114 } as DOMRect;
    const board = { left: 100, top: 100, width: 1200, height: 700 } as DOMRect;
    assert.equal(isRectCenterInside(visibleCard, viewport) && isRectCenterInside(visibleCard, board), true);
    const clippedBoard = { left: 800, top: 100, width: 600, height: 700 } as DOMRect;
    assert.equal(isRectCenterInside(visibleCard, clippedBoard), false);
});

test("open animation plays once per viewer session without an origin", () => {
    const projectUID = "board-gate";
    const cardUID = "card-gate";

    try {
        const now = 1_000;
        // First deep-link entry animates.
        assert.equal(shouldPlayCardOpenAnimation(projectUID, cardUID, false, now), true);
        markCardOpenAnimationPlayed(projectUID, cardUID, now);
        // A remount inside the suppression window (Suspense swap, re-key) must not replay.
        assert.equal(shouldPlayCardOpenAnimation(projectUID, cardUID, false, now + 200), false);
        // Another card in the same board is its own session.
        assert.equal(shouldPlayCardOpenAnimation(projectUID, "card-other", false, now + 200), true);
        // After the window, a genuinely new session animates again.
        assert.equal(shouldPlayCardOpenAnimation(projectUID, cardUID, false, now + OPEN_REPLAY_SUPPRESSION_MS + 1), true);
        // Closing the card ends the session immediately.
        markCardOpenAnimationPlayed(projectUID, cardUID, now);
        clearCardOpenAnimationSession(projectUID, cardUID);
        assert.equal(shouldPlayCardOpenAnimation(projectUID, cardUID, false, now + 100), true);
    } finally {
        clearCardOpenAnimationSession(projectUID, cardUID);
    }
});

test("click-open with a captured origin always animates, even after a recent play", () => {
    const projectUID = "board-origin";
    const cardUID = "card-origin";

    try {
        const now = 5_000;
        markCardOpenAnimationPlayed(projectUID, cardUID, now);
        assert.equal(shouldPlayCardOpenAnimation(projectUID, cardUID, true, now + 50), true);
    } finally {
        clearCardOpenAnimationSession(projectUID, cardUID);
    }
});
