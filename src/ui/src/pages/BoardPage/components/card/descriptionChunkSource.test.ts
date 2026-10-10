import assert from "node:assert/strict";
import test from "node:test";
import { unified } from "unified";
import remarkParse from "remark-parse";
import remarkGfm from "remark-gfm";
import { descriptionChunkSource } from "./descriptionChunkSource.ts";

test("chunk rendering preserves explicitly supplied ordered markers and nested lists", () => {
    const content = "# Heading\n\n3. first\n9. second\n   * nested\n2. third\n\nAfter";
    const root = unified().use(remarkParse).use(remarkGfm).parse(content);
    assert.equal(descriptionChunkSource(content, [root.children[1]]), "3. first\n9. second\n   * nested\n2. third");
    assert.equal(descriptionChunkSource(content, root.children), content);
});

test("chunks retain code fence, whitespace, link and image source spelling", () => {
    const content = "~~~txt\n2. literal\n~~~\n\n![caption](image.png)\n\n[reference][ref]\n\n[ref]: https://example.test";
    const root = unified().use(remarkParse).use(remarkGfm).parse(content);
    assert.equal(descriptionChunkSource(content, root.children), content);
    assert.equal(descriptionChunkSource(content, [root.children[0]]), "~~~txt\n2. literal\n~~~");
});

test("missing or invalid parser positions retain content rather than regenerating it", () => {
    assert.equal(descriptionChunkSource("original", [{}]), "original");
    assert.equal(descriptionChunkSource("original", []), "");
});
