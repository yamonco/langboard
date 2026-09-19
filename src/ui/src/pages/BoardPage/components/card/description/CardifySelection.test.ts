import assert from "node:assert/strict";
import test from "node:test";
import { buildCardLink, deriveCardTitle, isCardifiableSelection, replaceSelectionWithLink } from "./CardifySelection.ts";

test("derives a title from the first meaningful line", () => {
    assert.equal(deriveCardTitle("# Header\nBody text"), "Header");
    assert.equal(deriveCardTitle("- List item\nMore"), "List item");
    assert.equal(deriveCardTitle("  \n\nActual content"), "Actual content");
    assert.equal(deriveCardTitle(""), "Untitled");
});

test("truncates long titles with ellipsis", () => {
    const long = "a".repeat(100);
    const title = deriveCardTitle(long, 80);
    assert.equal(title.length, 80);
    assert.ok(title.endsWith("..."));
});

test("builds the [[link]] markdown", () => {
    assert.equal(buildCardLink("My Card"), "[[My Card]]");
});

test("replaces selection with link in full markdown", () => {
    const full = "Before\nSelected text\nAfter";
    const result = replaceSelectionWithLink(full, "Selected text", "[[New Card]]");
    assert.equal(result, "Before\n[[New Card]]\nAfter");
});

test("returns original when selection not found", () => {
    const full = "Hello world";
    const result = replaceSelectionWithLink(full, "missing", "[[X]]");
    assert.equal(result, "Hello world");
});

test("validates cardifiable selections", () => {
    assert.equal(isCardifiableSelection("valid text"), true);
    assert.equal(isCardifiableSelection("  "), false);
    assert.equal(isCardifiableSelection("ab"), false);
    assert.equal(isCardifiableSelection("a".repeat(20000)), false);
});
