import assert from "node:assert/strict";
import { test } from "node:test";
import { createSlateEditor, ElementApi } from "platejs";
import { MarkdownPlugin } from "@platejs/markdown";
import { BaseListPlugin } from "@platejs/list";
import { BaseCodeBlockPlugin, BaseCodeLinePlugin } from "@platejs/code-block";
import { BaseImagePlugin } from "@platejs/media";
import { preserveListNumbers, serializeListNumbers, formatOrderedList } from "./list-number.ts";
import { autoformatBlock } from "@platejs/autoformat";
import remarkGfm from "remark-gfm";

function roundTrip(source: string) {
    const editor = createSlateEditor({
        plugins: [
            MarkdownPlugin.configure({ options: { remarkPlugins: [remarkGfm] } }),
            BaseListPlugin,
            BaseCodeBlockPlugin,
            BaseCodeLinePlugin,
            BaseImagePlugin,
        ],
    });
    const value = preserveListNumbers(editor, source, editor.api.markdown.deserialize(source));
    assert.ok(value.every(ElementApi.isElement));
    editor.tf.setValue(value);
    editor.tf.normalize({ force: true });
    const saved = serializeListNumbers(editor);
    const reloaded = preserveListNumbers(editor, saved, editor.api.markdown.deserialize(saved));
    return { value: editor.children, saved, reloaded };
}

test("arbitrary markers survive conversion, native normalization and reload", () => {
    const { value, saved, reloaded } = roundTrip("3. Three\n9. Nine\n2. Two");
    assert.deepEqual(
        value.map((node) => node.listStart ?? 1),
        [3, 9, 2]
    );
    assert.equal(saved.trim(), "3. Three\n9. Nine\n2. Two");
    assert.deepEqual(
        reloaded.map((node) => node.listStart ?? 1),
        [3, 9, 2]
    );
});

test("nested markers use their own widths and levels", () => {
    const { saved, reloaded } = roundTrip("3. Three\n100. Hundred\n\n     8. Eight\n     2. Two\n9. Nine");
    assert.match(saved, /100\. Hundred\n\s+8\. Eight\n\s+2\. Two/);
    assert.deepEqual(
        reloaded.map((node) => node.listStart ?? 1),
        [3, 100, 8, 2, 9]
    );
    assert.deepEqual(
        reloaded.map((node) => node.indent),
        [1, 1, 2, 2, 1]
    );
});

test("code markers, unordered lists and image URLs are not numeric items", () => {
    const { saved } = roundTrip("```\n9. literal\n2. code\n```\n\n- Plain\n\n3. ![image](https://example.com/image.png)\n9. End");
    assert.match(saved, /9\. literal\n2\. code/);
    assert.match(saved, /https:\/\/example.com\/image.png/);
    assert.match(saved, /3\. .*\n(?:\n)?9\. End/);
});

test("native autoformat retains an explicit later item and parenthesis marker", () => {
    for (const marker of ["2.", "9)"]) {
        const editor = createSlateEditor({
            plugins: [BaseListPlugin],
            value: [
                { type: "p", indent: 1, listStyleType: "decimal", listRestart: 3, listStart: 3, children: [{ text: "Three" }] },
                { type: "p", children: [{ text: marker }] },
            ],
        });
        editor.tf.select({ path: [1, 0], offset: marker.length });
        assert.equal(
            autoformatBlock(editor, {
                match: [String.raw`^\d+\.$ `, String.raw`^\d+\)$ `],
                matchByRegex: true,
                mode: "block",
                type: "list",
                text: " ",
                format: formatOrderedList,
            }),
            true
        );
        editor.tf.normalize({ force: true });
        assert.equal(editor.children[1].listStart, Number.parseInt(marker, 10));
    }
});

test("a supplied value serializes independently without mutating editor state", () => {
    const editor = createSlateEditor({ plugins: [MarkdownPlugin, BaseListPlugin], value: [{ type: "p", children: [{ text: "Untouched" }] }] });
    const original = JSON.stringify(editor.children);
    const source = "7. Seven\n2. Two";
    const value = preserveListNumbers(editor, source, editor.api.markdown.deserialize(source));
    assert.equal(serializeListNumbers(editor, { value }).trim(), source);
    assert.equal(serializeListNumbers(editor, { value, remarkStringifyOptions: { incrementListMarker: false } }).trim(), source);
    assert.equal(JSON.stringify(editor.children), original);
});

test("GFM checklist state survives next to arbitrary numeric markers", () => {
    const { saved } = roundTrip("- [x] Checked\n- [ ] Pending\n\n3. Three\n9. Nine\n2. Two");
    assert.match(saved, /\[x\] Checked/);
    assert.match(saved, /\[ \] Pending/);
    assert.match(saved, /3\. Three\n9\. Nine\n2\. Two/);
});
