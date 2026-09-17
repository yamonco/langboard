import assert from "node:assert/strict";
import test from "node:test";
import {
    RELATIONSHIP_HOLD_CIRCUMFERENCE,
    RELATIONSHIP_HOLD_OPEN_MS,
    relationshipHoldProgress,
    relationshipHoldStrokeOffset,
} from "./BoardRelationshipHoldProgress.ts";

test("relationship hold progress reports a bounded desktop dwell", () => {
    assert.equal(relationshipHoldProgress(-1), 0);
    assert.equal(relationshipHoldProgress(Number.NaN), 0);
    assert.equal(relationshipHoldProgress(RELATIONSHIP_HOLD_OPEN_MS), 1);
});

test("relationship hold ring maps progress to clockwise stroke offset", () => {
    assert.equal(relationshipHoldStrokeOffset(0), RELATIONSHIP_HOLD_CIRCUMFERENCE);
    assert.equal(relationshipHoldStrokeOffset(500), RELATIONSHIP_HOLD_CIRCUMFERENCE * 0.75);
    assert.equal(relationshipHoldStrokeOffset(Number.MAX_SAFE_INTEGER), 0);
});
