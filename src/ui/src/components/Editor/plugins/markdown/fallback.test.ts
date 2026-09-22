import assert from "node:assert/strict";
import { test } from "node:test";
import { createSlateEditor } from "platejs";
import { MarkdownPlugin, remarkMdx } from "@platejs/markdown";
import { deserialize } from "./escape.ts";

test("invalid MDX preserves the block/inline document contract", () => {
    const editor = createSlateEditor({
        plugins: [MarkdownPlugin.configure({ options: { remarkPlugins: [remarkMdx] } })],
    });
    const source = "A log containing an unmatched {expression";
    assert.deepEqual(deserialize(false)(editor, source), [{ type: "p", children: [{ text: source }] }]);
    assert.deepEqual(deserialize(true)(editor, source), [{ text: source }]);
});
