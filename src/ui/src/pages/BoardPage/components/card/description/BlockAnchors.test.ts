import assert from "node:assert/strict";
import test from "node:test";
import { findAnchorAtLine, parseBlockAnchors } from "./BlockAnchors.ts";

test("parses headings as anchors", () => {
    const md = "# Title\n## Section\nContent";
    const { anchors, total_blocks } = parseBlockAnchors(md);
    assert.equal(total_blocks, 3);
    const headings = anchors.filter((a) => a.type === "heading");
    assert.equal(headings.length, 2);
    assert.equal(headings[0].text, "Title");
    assert.equal(headings[1].text, "Section");
});

test("groups consecutive list items into one anchor", () => {
    const md = "- item 1\n- item 2\n- item 3\n\nParagraph";
    const { anchors } = parseBlockAnchors(md);
    const lists = anchors.filter((a) => a.type === "list");
    assert.equal(lists.length, 1);
    assert.ok(lists[0].text.includes("item 1"));
    assert.ok(lists[0].text.includes("item 3"));
});

test("detects code blocks", () => {
    const md = "Before\n```js\nconst x = 1;\n```\nAfter";
    const { anchors } = parseBlockAnchors(md);
    const codeBlocks = anchors.filter((a) => a.type === "code");
    assert.equal(codeBlocks.length, 1);
    assert.ok(codeBlocks[0].text.includes("code block"));
});

test("handles standalone paragraphs", () => {
    const md = "First para.\n\nSecond para.";
    const { anchors } = parseBlockAnchors(md);
    const paras = anchors.filter((a) => a.type === "paragraph");
    assert.equal(paras.length, 2);
    assert.equal(paras[0].text, "First para.");
    assert.equal(paras[1].text, "Second para.");
});

test("handles empty markdown", () => {
    const { anchors, total_blocks } = parseBlockAnchors("");
    assert.equal(total_blocks, 0);
    assert.equal(anchors.length, 0);
});

test("generates unique anchor IDs", () => {
    const md = "# A\n# B\n# C";
    const { anchors } = parseBlockAnchors(md);
    const ids = new Set(anchors.map((a) => a.id));
    assert.equal(ids.size, anchors.length);
});

test("finds anchor at a given line", () => {
    const md = "# Header\n\nSome text here\n\n- list item";
    const { anchors } = parseBlockAnchors(md);
    const found = findAnchorAtLine(anchors, 2); // line 2 = "Some text here"
    assert.ok(found);
    assert.equal(found.type, "paragraph");
});

test("returns null for line before first anchor", () => {
    const md = "\n\n# Header";
    const { anchors } = parseBlockAnchors(md);
    const found = findAnchorAtLine(anchors, 0);
    assert.equal(found, null);
});
