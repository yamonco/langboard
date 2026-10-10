import assert from "node:assert/strict";
import test from "node:test";
import { relationshipFocusAction } from "./BoardRelationshipFocus.ts";

test("title enters the preview; backward title navigation remains native", () => {
    assert.equal(relationshipFocusAction("Tab", false, true, -1, 2), "first");
    assert.equal(relationshipFocusAction("Tab", true, true, -1, 2), undefined);
    assert.equal(relationshipFocusAction("Tab", false, true, -1, 0), undefined);
});

test("preview boundaries return to the source or continue after it without trapping focus", () => {
    assert.equal(relationshipFocusAction("Tab", true, false, 0, 2), "source");
    assert.equal(relationshipFocusAction("Tab", false, false, 1, 2), "next");
    assert.equal(relationshipFocusAction("Tab", false, false, 0, 2), undefined);
    assert.equal(relationshipFocusAction("Tab", true, false, 1, 2), undefined);
    assert.equal(relationshipFocusAction("Tab", false, false, -1, 2), undefined);
});

test("Escape dismisses only this interaction; other controls and keys remain unaffected", () => {
    assert.equal(relationshipFocusAction("Escape", false, true, -1, 2), "dismiss");
    assert.equal(relationshipFocusAction("Escape", false, false, 0, 2), "dismiss");
    assert.equal(relationshipFocusAction("Escape", false, false, -1, 2), undefined);
    assert.equal(relationshipFocusAction("Enter", false, true, -1, 2), undefined);
});
