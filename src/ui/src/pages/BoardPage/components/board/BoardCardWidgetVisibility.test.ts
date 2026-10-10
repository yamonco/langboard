import assert from "node:assert/strict";
import test from "node:test";
import { getBoardCardWidgetVisibility } from "./BoardCardWidgetVisibility.ts";

test("title-only cards show no description or comment widgets", () => {
    assert.deepEqual(getBoardCardWidgetVisibility({ has_description: false, count_comment: 0 }), {
        showDescriptionIcon: false,
        showCommentCount: false,
    });
});

test("cards with body content show the description icon", () => {
    assert.deepEqual(getBoardCardWidgetVisibility({ has_description: true, count_comment: 0 }), {
        showDescriptionIcon: true,
        showCommentCount: false,
    });
});

test("cards with comments show the count even without body content", () => {
    assert.deepEqual(getBoardCardWidgetVisibility({ has_description: false, count_comment: 3 }), {
        showDescriptionIcon: false,
        showCommentCount: true,
    });
});

test("missing summary fields fall back to a minimal card", () => {
    assert.deepEqual(getBoardCardWidgetVisibility({}), {
        showDescriptionIcon: false,
        showCommentCount: false,
    });
});
