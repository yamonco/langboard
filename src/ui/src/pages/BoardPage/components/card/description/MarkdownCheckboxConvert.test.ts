import assert from "node:assert/strict";
import test from "node:test";
import { convertMarkdownCheckboxes, hasMarkdownCheckboxes, parseCheckboxes, stripCheckboxLines } from "./MarkdownCheckboxConvert.ts";

test("detects markdown checkboxes", () => {
    assert.equal(hasMarkdownCheckboxes("- [ ] task\n- [x] done"), true);
    assert.equal(hasMarkdownCheckboxes("* [ ] task"), true);
    assert.equal(hasMarkdownCheckboxes("+ [x] done"), true);
    assert.equal(hasMarkdownCheckboxes("1. [ ] numbered"), true);
    assert.equal(hasMarkdownCheckboxes("no checkboxes here"), false);
    assert.equal(hasMarkdownCheckboxes("- [ ]"), false);
});

test("parses checkbox items with completion state", () => {
    const md = "- [ ] alpha\n- [x] beta\n* [X] gamma\n1. [ ] delta";
    const items = parseCheckboxes(md);
    assert.deepEqual(items.map((i) => i.title), ["alpha", "beta", "gamma", "delta"]);
    assert.deepEqual(items.map((i) => i.is_checked), [false, true, true, false]);
});

test("ignores empty checkbox titles", () => {
    const items = parseCheckboxes("- [ ]\n- [ ] real");
    assert.equal(items.length, 1);
    assert.equal(items[0].title, "real");
});

test("strips checkbox lines preserving other content", () => {
    const md = "# Header\n\n- [ ] task1\n- [x] task2\n\nParagraph text";
    const result = stripCheckboxLines(md);
    assert.ok(result.includes("# Header"));
    assert.ok(result.includes("Paragraph text"));
    assert.ok(!result.includes("[ ]"));
    assert.ok(!result.includes("[x]"));
});

test("full conversion returns items and remaining markdown", () => {
    const md = "Intro\n- [ ] a\n- [x] b\nOutro";
    const result = convertMarkdownCheckboxes(md);
    assert.equal(result.items.length, 2);
    assert.ok(result.remaining_markdown.includes("Intro"));
    assert.ok(result.remaining_markdown.includes("Outro"));
    assert.ok(!result.remaining_markdown.includes("[ ]"));
});

test("returns original when no checkboxes", () => {
    const md = "plain text only";
    const result = convertMarkdownCheckboxes(md);
    assert.equal(result.items.length, 0);
    assert.equal(result.remaining_markdown, md);
});
