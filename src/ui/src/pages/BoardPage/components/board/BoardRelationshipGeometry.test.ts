import assert from "node:assert/strict";
import test from "node:test";
import { getRelationshipDirection, intersectRelationshipRects, relationshipCurve } from "./BoardRelationshipGeometry.ts";

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
