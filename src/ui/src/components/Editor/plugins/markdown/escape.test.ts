import assert from "node:assert/strict";
import { test } from "node:test";
import { createSlateEditor, NodeApi, type Value } from "platejs";
import { MarkdownPlugin, remarkMdx } from "@platejs/markdown";
import { BaseTablePlugin } from "@platejs/table";
import remarkGfm from "remark-gfm";
import { deserialize } from "./escape.ts";
import { normalizeBreakTags } from "./normalize-break-tags.ts";

test("invalid MDX falls back to a renderable block, not a root text leaf", () => {
    const editor = createSlateEditor({
        plugins: [MarkdownPlugin.configure({ options: { remarkPlugins: [remarkGfm, remarkMdx] } })],
    });
    const source = "A log containing an unmatched {expression";
    assert.deepEqual(deserialize(false)(editor, source), [{ type: "p", children: [{ text: source }] }]);
    assert.deepEqual(deserialize(true)(editor, source), [{ text: source }]);
});

test("normalizes HTML break tags before markdown deserialization", () => {
    assert.equal(normalizeBreakTags("one<br>two<BR >three"), "one<br />two<br />three");
    assert.equal(normalizeBreakTags("one<br/>two<br />three"), "one<br />two<br />three");
});

test("does not rewrite literal break tags in code or escaped text", () => {
    const source = "`<br>` and \\<br> and &lt;br>\n\n```html\n<br>\n```";
    assert.equal(normalizeBreakTags(source), source);
});

test("all break spellings survive table deserialize, save and reload", () => {
    const editor = createSlateEditor({
        plugins: [BaseTablePlugin, MarkdownPlugin.configure({ options: { remarkPlugins: [remarkGfm, remarkMdx] } })],
    });
    for (const tag of ["<br>", "<br/>", "<br />", "<BR>"]) {
        const source = `| Kind | Scope |\n|---|---|\n| Action | First${tag}Second |`;
        const value = deserialize(false)(editor, source);
        assert.equal(NodeApi.string(value[0]), "KindScopeActionFirst\nSecond");
        editor.tf.setValue(value as Value);
        const saved = editor.api.markdown.serialize();
        assert.equal(NodeApi.string(deserialize(false)(editor, saved)[0]), "KindScopeActionFirst\nSecond");
    }
});
