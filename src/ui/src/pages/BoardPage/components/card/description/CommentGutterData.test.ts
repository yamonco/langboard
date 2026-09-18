import assert from "node:assert/strict";
import test from "node:test";
import { buildGutterModel, computeSectionCommentCounts, extractSectionAnchors } from "./CommentGutterData.ts";

test("groups comment counts by anchor", () => {
    const comments = [
        { uid: "1", section_anchor: "api" },
        { uid: "2", section_anchor: "api" },
        { uid: "3", section_anchor: "auth" },
        { uid: "4", section_anchor: null },
        { uid: "5" },
    ];
    const counts = computeSectionCommentCounts(comments);
    assert.deepEqual(counts, [
        { anchor: "api", count: 2 },
        { anchor: "auth", count: 1 },
    ]);
});

test("extracts section anchors from markdown headings", () => {
    const md = "# Title\n## API Changes\n### Auth Flow\nPlain text\n#### 한국어 섹션";
    const anchors = extractSectionAnchors(md);
    assert.deepEqual(anchors, ["title", "api-changes", "auth-flow", "한국어-섹션"]);
});

test("returns empty for markdown without headings", () => {
    assert.deepEqual(extractSectionAnchors("just text\nmore text"), []);
});

test("builds gutter model with zero-count sections", () => {
    const md = "## Alpha\n## Beta\n## Gamma";
    const comments = [
        { uid: "1", section_anchor: "beta" },
        { uid: "2", section_anchor: "beta" },
    ];
    const model = buildGutterModel(md, comments);
    assert.deepEqual(model, [
        { anchor: "alpha", count: 0 },
        { anchor: "beta", count: 2 },
        { anchor: "gamma", count: 0 },
    ]);
});

test("handles empty comments list", () => {
    const md = "## Only";
    const model = buildGutterModel(md, []);
    assert.deepEqual(model, [{ anchor: "only", count: 0 }]);
});

test("handles empty markdown", () => {
    const model = buildGutterModel("", [{ uid: "1", section_anchor: "x" }]);
    assert.deepEqual(model, []);
});
