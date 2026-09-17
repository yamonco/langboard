import assert from "node:assert/strict";
import { test } from "node:test";

import { areAnchorMarkersEqual } from "./anchorMarkers.ts";

const marker = { commentUID: "comment-1", quote: "same", commentPreview: "same", top: 12 };

test("keeps the previous marker array when pixel measurements are equivalent", () => {
    const previous = [marker];
    const next = [{ ...marker, top: 12.3 }];

    assert.equal(areAnchorMarkersEqual(previous, next), true);
});

test("detects changed comment markers", () => {
    assert.equal(areAnchorMarkersEqual([marker], [{ ...marker, commentUID: "comment-2" }]), false);
    assert.equal(areAnchorMarkersEqual([marker], []), false);
});
