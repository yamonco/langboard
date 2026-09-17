import assert from "node:assert/strict";
import test from "node:test";
import { escapeAngleOpenings } from "./escape-angles.ts";

test("escapes tag-like prose so parsers cannot read it as HTML or JSX", () => {
    assert.equal(escapeAngleOpenings("action=<a> missing=[x]"), "action=&lt;a> missing=[x]");
    assert.equal(escapeAngleOpenings("<tool> action=<a>"), "&lt;tool> action=&lt;a>");
});

test("keeps already-escaped backslash angles and plain text untouched", () => {
    assert.equal(escapeAngleOpenings("a \\< b"), "a \\< b");
    assert.equal(escapeAngleOpenings("no angles here"), "no angles here");
});

test("escapes every opening across multiple lines", () => {
    assert.equal(escapeAngleOpenings("x <p\ny <q> z"), "x &lt;p\ny &lt;q> z");
});
