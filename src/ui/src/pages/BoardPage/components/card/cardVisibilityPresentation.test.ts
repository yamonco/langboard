import assert from "node:assert/strict";
import { cardVisibilityPresentation } from "./cardVisibilityPresentation.ts";

assert.equal(cardVisibilityPresentation("INTERNAL", false), undefined);
assert.equal(cardVisibilityPresentation("INTERNAL", true), "whisper");
assert.equal(cardVisibilityPresentation("SHARED", true), undefined);
assert.equal(cardVisibilityPresentation("PRIVATE", false), "private");
assert.equal(cardVisibilityPresentation("PRIVATE", true), "private");
assert.equal(cardVisibilityPresentation(undefined, true), undefined);
