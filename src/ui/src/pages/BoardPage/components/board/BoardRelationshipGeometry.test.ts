import assert from "node:assert/strict";
import test from "node:test";
import {
    getRelationshipDirection,
    getVisibleRelationshipTarget,
    intersectRelationshipRects,
    relationshipCurve,
    relationshipAnchor,
    relationshipSideCounts,
} from "./BoardRelationshipGeometry.ts";

const board = { left: 0, top: 80, right: 1000, bottom: 700 };
const column = { left: 350, top: 160, right: 670, bottom: 550 };

test("clips cards against their column scrollport, not only the board", () => {
    const card = { left: 360, top: 560, right: 660, bottom: 620 };
    assert.ok(intersectRelationshipRects(card, board));
    assert.equal(intersectRelationshipRects(card, column), undefined);
    assert.equal(getRelationshipDirection(card, column), "down");
});

test("keeps partially visible cards attached to their visible bounds", () => {
    const card = { left: 360, top: 140, right: 660, bottom: 200 };
    assert.deepEqual(intersectRelationshipRects(card, column), { left: 360, top: 160, right: 660, bottom: 200 });
    assert.equal(getRelationshipDirection(card, column), undefined);
});

test("a visible footer cannot hide the offscreen title shortcut", () => {
    const card = { left: 360, top: 80, right: 660, bottom: 170 };
    const title = { left: 370, top: 90, right: 650, bottom: 130 };
    assert.ok(intersectRelationshipRects(card, column));
    assert.equal(getVisibleRelationshipTarget(card, column, title), undefined);
    assert.equal(getRelationshipDirection(title, column), "up");
});

test("a readable title keeps a partially clipped card attached", () => {
    const card = { left: 360, top: 140, right: 660, bottom: 230 };
    const title = { left: 370, top: 170, right: 650, bottom: 200 };
    assert.deepEqual(getVisibleRelationshipTarget(card, column, title), { left: 360, top: 160, right: 660, bottom: 230 });
    assert.deepEqual(getVisibleRelationshipTarget(card, column), intersectRelationshipRects(card, column));
});

test("excludes the floating navigation area from the usable board viewport", () => {
    const viewport = intersectRelationshipRects(board, { left: 0, top: 0, right: 1000, bottom: 640 });
    assert.deepEqual(viewport, { ...board, bottom: 640 });
    assert.equal(intersectRelationshipRects({ left: 400, top: 640, right: 600, bottom: 700 }, viewport!), undefined);
});

test("reports all four offscreen directions, with horizontal navigation first", () => {
    assert.equal(getRelationshipDirection({ left: -100, right: 0, top: 40, bottom: 70 }, board), "left");
    assert.equal(getRelationshipDirection({ left: 1000, right: 1100, top: 720, bottom: 800 }, board), "right");
    assert.equal(getRelationshipDirection({ left: 400, right: 600, top: 20, bottom: 80 }, board), "up");
    assert.equal(getRelationshipDirection({ left: 400, right: 600, top: 700, bottom: 800 }, board), "down");
});

test("parent and child hover produce the same directed relationship", () => {
    const parent = { x: 900, y: 200 };
    const child = { x: 400, y: 500 };
    assert.equal(relationshipCurve(parent, child, true), relationshipCurve(child, parent, false));
    assert.match(relationshipCurve(child, parent, false), /^M 900 200 C .*400 500$/);
});

test("connection anchors follow actual card position rather than relationship role", () => {
    const card = { left: 700, right: 1000, top: 200, bottom: 300 };
    assert.deepEqual(relationshipAnchor(card, { x: 400, y: 250 }), { x: 700, y: 250 });
    assert.deepEqual(relationshipAnchor(card, { x: 1200, y: 250 }), { x: 1000, y: 250 });
    assert.deepEqual(relationshipAnchor(card, { x: 850, y: 100 }), { x: 850, y: 200 });
    assert.deepEqual(relationshipAnchor(card, { x: 850, y: 500 }), { x: 850, y: 300 });
});

test("reversed columns bend toward the child while preserving arrow direction", () => {
    assert.equal(relationshipCurve({ x: 900, y: 200 }, { x: 400, y: 500 }, true), "M 900 200 C 690 200, 610 500, 400 500");
    assert.equal(relationshipCurve({ x: 400, y: 500 }, { x: 900, y: 200 }, false), "M 900 200 C 690 200, 610 500, 400 500");
    assert.equal(relationshipCurve({ x: 400, y: 200 }, { x: 900, y: 500 }, true), "M 400 200 C 610 200, 690 500, 900 500");
});

test("direction badges merge mixed roles and duplicate edges without guessing unloaded columns", () => {
    const targets = [
        { uid: "parent", order: 0 },
        { uid: "child", order: 0 },
        { uid: "child", order: 0 },
        { uid: "other", order: 4 },
        { uid: "same-column", order: 2 },
        { uid: "unloaded", order: undefined },
    ];
    assert.deepEqual(relationshipSideCounts(2, targets), { left: 2, right: 1 });
    assert.deepEqual(relationshipSideCounts(undefined, targets), { left: 0, right: 0 });
    assert.deepEqual(relationshipSideCounts(0, targets), { left: 0, right: 2 });
});
