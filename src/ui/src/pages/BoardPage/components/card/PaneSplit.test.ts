import assert from "node:assert/strict";
import test from "node:test";
import {
    PANE_DEFAULT_RATIO,
    PANE_MAX_RATIO,
    PANE_MIN_RATIO,
    clampPaneRatio,
    paneWidths,
    ratioFromPointer,
} from "./PaneSplit.ts";

test("spec range is 40% to 55%", () => {
    assert.equal(PANE_MIN_RATIO, 0.40);
    assert.equal(PANE_MAX_RATIO, 0.55);
    assert.ok(PANE_DEFAULT_RATIO >= PANE_MIN_RATIO);
    assert.ok(PANE_DEFAULT_RATIO <= PANE_MAX_RATIO);
});

test("clamps to range", () => {
    assert.equal(clampPaneRatio(0.30), 0.40);
    assert.equal(clampPaneRatio(0.60), 0.55);
    assert.equal(clampPaneRatio(0.45), 0.45);
});

test("handles NaN and Infinity", () => {
    assert.equal(clampPaneRatio(NaN), PANE_DEFAULT_RATIO);
    assert.equal(clampPaneRatio(Infinity), PANE_DEFAULT_RATIO);
    assert.equal(clampPaneRatio(-Infinity), PANE_DEFAULT_RATIO);
});

test("computes ratio from pointer position", () => {
    // Container 1000px wide, pointer at x=550 → comment pane = 45%
    assert.ok(Math.abs(ratioFromPointer(550, 1000) - 0.45) < 0.001);
    // Pointer at x=400 → 60% clamped to 55%
    assert.equal(ratioFromPointer(400, 1000), 0.55);
    // Pointer at x=650 → 35% clamped to 40%
    assert.equal(ratioFromPointer(650, 1000), 0.40);
});

test("handles zero-width container", () => {
    assert.equal(ratioFromPointer(500, 0), PANE_DEFAULT_RATIO);
});

test("derives CSS widths from ratio", () => {
    const w = paneWidths(0.45);
    assert.equal(w.description, "55%");
    assert.equal(w.comment, "45%");

    const w2 = paneWidths(0.40);
    assert.equal(w2.description, "60%");
    assert.equal(w2.comment, "40%");
});

test("paneWidths always sums to 100%", () => {
    for (const ratio of [0.40, 0.45, 0.50, 0.55]) {
        const w = paneWidths(ratio);
        const desc = parseInt(w.description);
        const comment = parseInt(w.comment);
        assert.equal(desc + comment, 100);
    }
});
