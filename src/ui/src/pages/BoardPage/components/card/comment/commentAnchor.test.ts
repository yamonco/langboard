import assert from "node:assert/strict";
import test from "node:test";
import { normalizeAnchorPreview, type ICardCommentAnchor, resolveCardCommentAnchorIndex } from "./commentAnchor.ts";

const anchor: ICardCommentAnchor = {
    type: "TextQuoteSelector",
    version: 1,
    exact: "durable identity",
    prefix: "Use a",
    suffix: "for comments",
    start_block: "Use a durable identity for comments",
    end_block: "Use a durable identity for comments",
    start_path: [0],
    end_path: [0],
};

test("follows an unchanged block when surrounding blocks move", () => {
    assert.equal(resolveCardCommentAnchorIndex(anchor, ["New introduction", anchor.start_block]), 1);
});

test("reattaches by the exact quote after the block is edited", () => {
    assert.equal(resolveCardCommentAnchorIndex(anchor, ["Use one durable identity for comments and tasks"]), 0);
});

test("preserves the quote when surrounding wording changes", () => {
    assert.equal(resolveCardCommentAnchorIndex(anchor, ["Unrelated", "Use a durable identity for threaded comments"]), 1);
});

test("creates a compact plain-text memo preview", () => {
    assert.equal(
        normalizeAnchorPreview("**Decision:** use [stable identity](https://example.test)\n> Keep email as metadata"),
        "Decision: use stable identity Keep email as metadata"
    );
});

test("a deleted quote never attaches to an unrelated block at the old path", () => {
    assert.equal(resolveCardCommentAnchorIndex(anchor, ["Completely unrelated replacement"]), null);
});

test("duplicate quotes use surrounding context instead of choosing the first block", () => {
    assert.equal(resolveCardCommentAnchorIndex(anchor, ["Keep a durable identity for records", "Use one durable identity for comments"]), 1);
});

test("indistinguishable duplicate blocks remain unresolved", () => {
    assert.equal(resolveCardCommentAnchorIndex(anchor, [anchor.start_block, anchor.start_block]), null);
});

test("quotes spanning adjacent blocks resolve to the starting block", () => {
    assert.equal(
        resolveCardCommentAnchorIndex({ ...anchor, exact: "durable identity for comments" }, [
            "New introduction",
            "Use a durable identity",
            "for comments",
        ]),
        1
    );
});
