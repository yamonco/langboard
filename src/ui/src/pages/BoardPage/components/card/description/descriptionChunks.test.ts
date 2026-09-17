import assert from "node:assert/strict";
import test from "node:test";

import { buildDescriptionChunks, getMarkdownNodeText } from "./descriptionChunks.ts";

test("buildDescriptionChunks starts each heading and keeps the original markdown", () => {
    const content = "# First\n\nalpha\n\nparagraph\n\n# Second\n\nbeta";
    const chunks = buildDescriptionChunks(content);

    assert.equal(chunks[0].metadata.type, "heading");
    assert.equal(chunks[0].metadata.heading, "First");
    assert.equal(chunks[1].metadata.type, "mixed");
    assert.equal(chunks[2].metadata.type, "heading");
    assert.equal(chunks[2].metadata.heading, "Second");
    const serialized = chunks
        .map((chunk) => chunk.content)
        .join("")
        .trim();
    for (const phrase of ["First", "alpha", "paragraph", "Second", "beta"]) {
        assert.match(serialized, new RegExp(phrase));
    }
});

test("heavy markdown blocks are isolated for predictable virtualization", () => {
    const list = Array.from({ length: 6 }, (_, index) => `${index + 1}. item`).join("\n");
    const content = `intro\n\n${list}\n\n| Left | Right |\n| --- | --- |\n| a | b |`;
    const chunks = buildDescriptionChunks(content);

    assert.equal(chunks.length, 3);
    assert.equal(chunks[0].metadata.type, "paragraph");
    assert.equal(chunks[1].metadata.type, "list");
    assert.equal(chunks[1].metadata.isHeavy, true);
    assert.equal(chunks[2].metadata.type, "table");
    assert.equal(chunks[2].metadata.isHeavy, true);
});

test("preview text is bounded without loading rendered content", () => {
    const content = `# Long section\n\n${"preview ".repeat(40)}`;
    const chunks = buildDescriptionChunks(content);

    assert.equal(chunks[1].metadata.previewText.length, 181);
    assert.equal(chunks[1].metadata.previewText.endsWith("…"), true);
    assert.equal(getMarkdownNodeText({ type: "text", value: "hello" }), "hello");
});
