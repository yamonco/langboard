import assert from "node:assert/strict";
import { describe, it } from "node:test";

import { clampCommentPanelWidth, getCommentPanelWidthBounds } from "./CommentPanelWidth.ts";

describe("comment panel width", () => {
    it("keeps the body usable while applying a viewer-relative maximum", () => {
        assert.deepEqual(getCommentPanelWidthBounds(800), { min: 280, max: 384 });
        assert.equal(clampCommentPanelWidth(500, 800), 384);
        assert.equal(clampCommentPanelWidth(200, 800), 280);
    });

    it("caps wide viewers and recovers from invalid saved preferences", () => {
        assert.equal(clampCommentPanelWidth(900, 1600), 560);
        assert.equal(clampCommentPanelWidth(Number.NaN, 1000), 360);
    });
});
