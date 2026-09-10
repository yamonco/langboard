import assert from "node:assert/strict";
import test from "node:test";
import { type ICardCommentAnchor, resolveCardCommentAnchorIndex } from "./commentAnchor.ts";

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

test("uses a close block match before the stale path hint", () => {
    assert.equal(resolveCardCommentAnchorIndex(anchor, ["Unrelated", "Use a durable identity for threaded comments"]), 1);
});
